"""Erinnerung an Angebote kurz vor Ablauf (ADR-009, I4).

Ablauf wie bei Mahnungen (ADR-004, ADR-006):
1. Täglicher Lauf schlägt je offenem Angebot höchstens eine Erinnerung vor, wenn es in höchstens X Tagen abläuft
   und der Kunde eine E-Mail-Adresse hat. Nichts wird automatisch versendet.
2. Freigabe nur durch Inhaber oder Freigeber, angemeldet mit zweitem Faktor; Versand als Job.
3. Frische-Check in Lexware vor dem Versand: angenommen, abgelehnt, gelöscht oder abgelaufen → verworfen.
4. Mail mit Absendername und Antwortadresse der Firma, Angebots-PDF aus Lexware im Anhang; alles protokolliert.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from email.utils import formataddr

from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import Firma, Nutzer
from audit.services import protokolliere
from connectors.base import ExternalRef
from connectors.fehler import ConnectorFehler
from connectors.services import aktive_verbindung, connector_fuer
from jobs.models import Job
from jobs.queue import enqueue
from jobs.worker import JobAbbruch
from ledger.models import Beleg

from .mail import MailInhalt, euro
from .mailversand import Zustellfehler, absender_adresse, senden
from .models import Angebotserinnerung
from .services import mahnplan_fuer
from .texte import ANGEBOT_STANDARD, ersetzen_angebot

log = logging.getLogger(__name__)


def _datum(tag: date | None) -> str:
    return tag.strftime("%d.%m.%Y") if tag else "–"


def vorschlaege_erzeugen(firma: Firma, heute: date | None = None) -> list[Angebotserinnerung]:
    heute = heute or timezone.localdate()
    plan = mahnplan_fuer(firma)
    if not plan.angebot_erinnerung_aktiv:
        return []
    kandidaten = (
        Beleg.objects.fuer(firma)
        .filter(
            art=Beleg.Art.ANGEBOT,
            status=Beleg.Status.OFFEN,
            gueltig_bis__gte=heute,
            gueltig_bis__lte=heute + timedelta(days=plan.angebot_erinnerung_tage),
            kontakt__isnull=False,
        )
        .exclude(kontakt__email="")
        .exclude(angebotserinnerungen__isnull=False)
        .select_related("kontakt")
    )
    neu = []
    for beleg in kandidaten:
        try:
            with transaction.atomic():
                neu.append(Angebotserinnerung.objects.create(firma=firma, beleg=beleg, gueltig_bis=beleg.gueltig_bis))
        except IntegrityError:
            continue  # parallel angelegt
    if neu:
        protokolliere(
            firma, "angebot.erinnerungen_vorgeschlagen", daten={"anzahl": len(neu), "datum": heute.isoformat()}
        )
    return neu


def inhalt(erinnerung: Angebotserinnerung) -> MailInhalt:
    """Vorschau und Versand nutzen dieselbe Funktion (wie D10 bei Mahnungen)."""
    firma = erinnerung.firma
    beleg = erinnerung.beleg
    kontakt = beleg.kontakt
    plan = mahnplan_fuer(firma)
    name = kontakt.name if kontakt else beleg.kontakt_name
    anrede = "Guten Tag" if (kontakt is None or kontakt.ist_unternehmen_extern is not False) else f"Guten Tag {name}"
    werte = {
        "kunde": name,
        "anrede": anrede,
        "angebotsnummer": beleg.nummer,
        "angebotsdatum": _datum(beleg.belegdatum),
        "gueltig_bis": _datum(beleg.gueltig_bis or erinnerung.gueltig_bis),
        "betrag": euro(beleg.brutto or Decimal("0.00")),
        "firma": firma.name,
        "signatur": firma.mahn_signatur or firma.name,
    }
    nummer = "".join(ch for ch in beleg.nummer if ch.isalnum() or ch in "-_") or str(beleg.pk)
    return MailInhalt(
        absender=formataddr((firma.email_absender or firma.name, absender_adresse(firma))),
        empfaenger=kontakt.email if kontakt else "",
        reply_to=firma.reply_to,
        bcc="",
        betreff=ersetzen_angebot(plan.betreff_angebot or ANGEBOT_STANDARD[0], werte).replace("\n", " ").strip(),
        text=ersetzen_angebot(plan.text_angebot or ANGEBOT_STANDARD[1], werte).strip() + "\n",
        anhang_name=f"Angebot_{nummer}.pdf",
    )


@dataclass
class Ergebnis:
    freigegeben: list[Angebotserinnerung] = field(default_factory=list)
    abgelehnt: list[tuple[Angebotserinnerung, str]] = field(default_factory=list)


def freigeben(firma: Firma, nutzer: Nutzer, ids: Iterable[int]) -> Ergebnis:
    """Freigabe (die View prüft Rolle; die Sitzung hat immer den zweiten Faktor). Fremde IDs werden ignoriert."""
    ergebnis = Ergebnis()
    heute = timezone.localdate()
    with transaction.atomic():
        for e in (
            Angebotserinnerung.objects.fuer(firma)
            .select_for_update(of=("self",))
            .filter(pk__in=list(ids))
            .select_related("beleg")
            .order_by("pk")
        ):
            if e.status != Angebotserinnerung.Status.VORGESCHLAGEN:
                ergebnis.abgelehnt.append((e, "ist nicht mehr zur Freigabe vorgesehen"))
                continue
            if e.beleg.status != Beleg.Status.OFFEN or (e.beleg.gueltig_bis and e.beleg.gueltig_bis < heute):
                ergebnis.abgelehnt.append((e, "ist nicht mehr offen"))
                continue
            e.status = Angebotserinnerung.Status.FREIGEGEBEN
            e.freigegeben_von = nutzer
            e.freigegeben_am = timezone.now()
            e.fehler = ""
            e.save(update_fields=["status", "freigegeben_von", "freigegeben_am", "fehler"])
            protokolliere(
                firma, "angebot.erinnerung_freigegeben", nutzer=nutzer, objekt=e, daten={"angebot": e.beleg.nummer}
            )
            enqueue(
                "dunning.angebot_erinnern",
                {"erinnerung_id": e.pk},
                firma=firma,
                eindeutig=f"angebot-erinnerung:{e.pk}",
                max_versuche=5,
            )
            ergebnis.freigegeben.append(e)
    return ergebnis


def verwerfen(erinnerung: Angebotserinnerung, nutzer: Nutzer | None, grund: str) -> None:
    if erinnerung.status not in (Angebotserinnerung.Status.VORGESCHLAGEN, Angebotserinnerung.Status.FEHLER):
        raise ValueError("Diese Erinnerung kann nicht mehr verworfen werden.")
    erinnerung.status = Angebotserinnerung.Status.VERWORFEN
    erinnerung.verworfen_grund = grund[:300]
    erinnerung.save(update_fields=["status", "verworfen_grund"])
    protokolliere(
        erinnerung.firma, "angebot.erinnerung_verworfen", nutzer=nutzer, objekt=erinnerung, daten={"grund": grund[:300]}
    )


class _Abbruch(Exception):
    """Dauerhafter Fehler, der an der Erinnerung sichtbar wird."""


def _verwerfen_frisch(e: Angebotserinnerung, grund: str) -> None:
    e.status = Angebotserinnerung.Status.VERWORFEN
    e.verworfen_grund = grund
    e.save(update_fields=["status", "verworfen_grund"])
    protokolliere(e.firma, "angebot.erinnerung_frischecheck", objekt=e, daten={"grund": grund})


def versenden(e: Angebotserinnerung) -> None:
    if e.status != Angebotserinnerung.Status.FREIGEGEBEN:
        return
    if e.message_id:  # Mail ging bereits hinaus (z. B. Absturz direkt danach): nur noch den Status nachziehen
        Angebotserinnerung.objects.filter(pk=e.pk).update(status=Angebotserinnerung.Status.VERSENDET)
        return
    verbindung = aktive_verbindung(e.firma)
    if verbindung is None:
        raise _Abbruch("Keine aktive Verbindung zu Lexware.")
    connector = connector_fuer(verbindung)
    beleg = e.beleg
    info = connector.get_quotation(beleg.extern_id)
    heute = timezone.localdate()
    if info is None:
        _verwerfen_frisch(e, "Das Angebot gibt es in Lexware nicht mehr.")
        return
    if info.status != "offen":
        beleg.status = info.status
        beleg.save(update_fields=["status"])
        _verwerfen_frisch(
            e, f"Das Angebot ist inzwischen {beleg.get_status_display()} (Frische-Check vor dem Versand)."
        )
        return
    if info.gueltig_bis and info.gueltig_bis < heute:
        _verwerfen_frisch(e, "Das Angebot ist inzwischen abgelaufen.")
        return
    if info.gueltig_bis != beleg.gueltig_bis:
        beleg.gueltig_bis = info.gueltig_bis
        beleg.save(update_fields=["gueltig_bis"])
    pdf = connector.get_pdf(ExternalRef("quotation", beleg.extern_id))
    mail = inhalt(e)
    message_id = senden(e.firma, mail, pdf)
    e.status = Angebotserinnerung.Status.VERSENDET
    e.versendet_am = timezone.now()
    e.empfaenger = mail.empfaenger
    e.message_id = message_id
    e.fehler = ""
    e.save(update_fields=["status", "versendet_am", "empfaenger", "message_id", "fehler"])
    protokolliere(
        e.firma,
        "angebot.erinnerung_versendet",
        nutzer=e.freigegeben_von,
        objekt=e,
        daten={"angebot": beleg.nummer, "message_id": message_id},
    )


def _fehler(e: Angebotserinnerung, text: str) -> None:
    Angebotserinnerung.objects.filter(pk=e.pk).update(status=Angebotserinnerung.Status.FEHLER, fehler=text[:2000])
    protokolliere(e.firma, "angebot.erinnerung_fehler", objekt=e, daten={"fehler": text[:300]})


def versand_job(job: Job) -> None:
    e = (
        Angebotserinnerung.objects.select_related("beleg", "beleg__kontakt", "firma", "freigegeben_von")
        .filter(pk=job.payload.get("erinnerung_id"), firma_id=job.firma_id)
        .first()
    )
    if e is None:
        raise JobAbbruch("Erinnerung nicht gefunden")
    try:
        versenden(e)
    except (_Abbruch, Zustellfehler) as fehler:
        _fehler(e, str(fehler))
        raise JobAbbruch(str(fehler)) from fehler
    except ConnectorFehler as fehler:
        if not fehler.wiederholbar:
            _fehler(e, f"{fehler.meldung} ({fehler})")
            raise JobAbbruch(str(fehler)) from fehler
        if job.versuche + 1 >= job.max_versuche:
            _fehler(e, fehler.meldung)
        raise
    except Exception:
        if job.versuche + 1 >= job.max_versuche:
            _fehler(e, "Der Versand ist fehlgeschlagen. Bitte versuchen Sie es erneut.")
        log.exception("Versand der Angebotserinnerung fehlgeschlagen", extra={"erinnerung_id": e.pk})
        raise
