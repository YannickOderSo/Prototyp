"""Versand einer freigegebenen Erinnerung oder Mahnung (M2-05, D7, D9, B6).

Ablauf:
1. Nur Vorschläge im Status „freigegeben“ (idempotent; ein vorhandener Versand-Datensatz verhindert Doppelversand).
2. Frische-Check: Zahlstatus in Lexware neu abfragen. Bezahlt → verwerfen. Offener Betrag geändert →
   neu berechnen und erneut zur Freigabe stellen. Nichts wird versendet.
3. Stufe 0: Rechnungs-PDF aus Lexware. Stufe 1 und 2: Mahnungsentwurf in Lexware anlegen (nie finalisieren),
   dann dessen PDF holen. Die Mahnungs-ID wird sofort gespeichert, damit ein Neuversuch keinen zweiten Entwurf anlegt.
4. Ohne E-Mail-Adresse: PDF für den Postversand bereitstellen. Sonst E-Mail mit Anhang senden.
5. Versand-Datensatz, Status, Mahnstufe am Beleg und Protokoll.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from audit.services import protokolliere
from connectors.base import DunningFees, ExternalRef
from connectors.fehler import ConnectorFehler
from connectors.services import aktive_verbindung, connector_fuer
from jobs.models import Job
from jobs.worker import JobAbbruch
from ledger.models import Beleg

from . import mahnschreiben
from .mail import inhalt, zinsberechnung_text
from .mailversand import Zustellfehler, senden
from .models import Mahnvorschlag, Versand
from .texte import GEGENSTANDSLOS
from .vorschlaege import neu_berechnen

log = logging.getLogger(__name__)


class VersandAbgebrochen(Exception):
    """Dauerhafter Fehler, der am Vorschlag sichtbar wird."""


def _fehler(vorschlag: Mahnvorschlag, text: str) -> None:
    Mahnvorschlag.objects.filter(pk=vorschlag.pk).update(status=Mahnvorschlag.Status.FEHLER, fehler=text[:2000])
    protokolliere(vorschlag.firma, "mahnung.fehler", objekt=vorschlag, daten={"fehler": text[:300]})


def _frische_check(vorschlag: Mahnvorschlag, zahlung_offen: Decimal, bezahlt: bool) -> bool:
    """True, wenn der Versand weitergehen darf."""
    beleg = vorschlag.beleg
    heute = timezone.localdate()
    if bezahlt:
        beleg.offen = zahlung_offen
        beleg.status = Beleg.Status.BEZAHLT
        beleg.save(update_fields=["offen", "status"])
        vorschlag.status = Mahnvorschlag.Status.VERWORFEN
        vorschlag.verworfen_grund = "Inzwischen bezahlt (Frische-Check vor dem Versand)."
        vorschlag.save(update_fields=["status", "verworfen_grund"])
        protokolliere(vorschlag.firma, "mahnung.frischecheck_bezahlt", objekt=vorschlag)
        return False
    if zahlung_offen != vorschlag.offen_betrag:
        alt = vorschlag.offen_betrag
        beleg.offen = zahlung_offen
        beleg.save(update_fields=["offen"])
        vorschlag.refresh_from_db()
        neu_berechnen(vorschlag, heute)
        vorschlag.status = Mahnvorschlag.Status.VORGESCHLAGEN
        vorschlag.freigegeben_von = None
        vorschlag.freigegeben_am = None
        vorschlag.hinweise = [
            f"Der offene Betrag hat sich {'in Belegfluss' if beleg.importiert else 'in Lexware'} geändert "
            f"({alt} → {zahlung_offen}). Bitte erneut freigeben.",
            *vorschlag.hinweise,
        ]
        vorschlag.save()
        protokolliere(
            vorschlag.firma,
            "mahnung.frischecheck_geaendert",
            objekt=vorschlag,
            daten={"alt": str(alt), "neu": str(zahlung_offen)},
        )
        return False
    return True


def _pdf_importiert(vorschlag: Mahnvorschlag) -> bytes | None:
    """ADR-008: Zahlstatus aus dem Cockpit statt aus Lexware; Mahnschreiben erzeugt die App."""
    beleg = vorschlag.beleg
    beleg.refresh_from_db()
    if not _frische_check(vorschlag, beleg.offen, beleg.status == Beleg.Status.BEZAHLT or beleg.offen <= 0):
        raise _KeinVersand
    if vorschlag.stufe == 0:
        return None  # Erinnerung per Mail ohne Anhang; für den Postversand erzeugt versenden() den Brief
    return mahnschreiben.pdf(vorschlag)


def _pdf_holen(vorschlag: Mahnvorschlag) -> bytes | None:
    beleg = vorschlag.beleg
    if beleg.importiert:
        return _pdf_importiert(vorschlag)
    verbindung = aktive_verbindung(vorschlag.firma)
    if verbindung is None:
        raise VersandAbgebrochen("Keine aktive Verbindung zu Lexware.")
    connector = connector_fuer(verbindung)
    zahlung = connector.get_payment_status(beleg.extern_id)
    if not _frische_check(vorschlag, zahlung.offen, zahlung.bezahlt):
        raise _KeinVersand
    if vorschlag.stufe == 0:
        art = "downpaymentinvoice" if beleg.art == Beleg.Art.ABSCHLAG else "invoice"
        return connector.get_pdf(ExternalRef(art, beleg.extern_id))  # type: ignore[arg-type]
    if not vorschlag.lexware_dunning_id:
        gebuehren = DunningFees(
            stufe=vorschlag.stufe,
            rechnungsnummer=beleg.nummer,
            offen=vorschlag.offen_betrag,
            zinsen=vorschlag.zinsen,
            pauschale=vorschlag.pauschale,
            zinsen_text=zinsberechnung_text(vorschlag),
            einleitung=(
                f"Zu unserer Rechnung {beleg.nummer} konnten wir noch keinen vollständigen Zahlungseingang feststellen."
            ),
            bemerkung=GEGENSTANDSLOS,
            belegdatum=timezone.localdate(),
        )
        ref = connector.create_dunning_draft(beleg.extern_id, gebuehren)
        if ref is None:
            raise VersandAbgebrochen("Das Bestandstool kann keine Mahnungen anlegen.")
        vorschlag.lexware_dunning_id = ref.extern_id
        Mahnvorschlag.objects.filter(pk=vorschlag.pk).update(lexware_dunning_id=ref.extern_id)
        protokolliere(
            vorschlag.firma, "lexware.mahnungsentwurf_angelegt", objekt=vorschlag, daten={"id": ref.extern_id}
        )
    return connector.get_pdf(ExternalRef("dunning", vorschlag.lexware_dunning_id))


class _KeinVersand(Exception):
    pass


def versenden(vorschlag: Mahnvorschlag) -> None:
    if vorschlag.status != Mahnvorschlag.Status.FREIGEGEBEN:
        return
    if Versand.objects.filter(vorschlag=vorschlag).exists():
        # Mail ging bereits hinaus (z. B. Absturz direkt danach): nur noch den Status nachziehen
        Mahnvorschlag.objects.filter(pk=vorschlag.pk).update(status=Mahnvorschlag.Status.VERSENDET)
        return
    try:
        pdf = _pdf_holen(vorschlag)
    except _KeinVersand:
        return
    mail = inhalt(vorschlag)
    if vorschlag.versandart == "post" or not mail.empfaenger:
        if pdf is None:
            pdf = mahnschreiben.pdf(vorschlag)
        vorschlag.pdf = pdf
        vorschlag.pdf_name = mail.anhang_name
        vorschlag.status = Mahnvorschlag.Status.POST_BEREIT
        vorschlag.save(update_fields=["pdf", "pdf_name", "status"])
        protokolliere(vorschlag.firma, "mahnung.post_bereit", objekt=vorschlag)
        return
    message_id = senden(vorschlag.firma, mail, pdf)
    with transaction.atomic():
        Versand.objects.create(
            firma=vorschlag.firma,
            vorschlag=vorschlag,
            empfaenger=mail.empfaenger,
            betreff=mail.betreff,
            text=mail.text,
            anhang_name=mail.anhang_name,
            message_id=message_id,
        )
        vorschlag.status = Mahnvorschlag.Status.VERSENDET
        vorschlag.versendet_am = timezone.now()
        vorschlag.fehler = ""
        vorschlag.save(update_fields=["status", "versendet_am", "fehler"])
        beleg = vorschlag.beleg
        beleg.mahnstufe = max(beleg.mahnstufe, vorschlag.stufe + 1)
        beleg.save(update_fields=["mahnstufe"])
        protokolliere(
            vorschlag.firma,
            "mahnung.versendet",
            nutzer=vorschlag.freigegeben_von,
            objekt=vorschlag,
            daten={
                "stufe": vorschlag.stufe,
                "beleg": beleg.nummer,
                "gesamt": str(vorschlag.gesamt),
                "message_id": message_id,
            },
        )


def versand_job(job: Job) -> None:
    """Job-Handler: dauerhafte Fehler sofort sichtbar; vorübergehende werden wiederholt, der letzte wird sichtbar."""
    vorschlag = (
        Mahnvorschlag.objects.select_related("beleg", "beleg__kontakt", "firma", "freigegeben_von")
        .filter(pk=job.payload.get("vorschlag_id"), firma_id=job.firma_id)
        .first()
    )
    if vorschlag is None:
        raise JobAbbruch("Vorschlag nicht gefunden")
    try:
        versenden(vorschlag)
    except (VersandAbgebrochen, Zustellfehler) as fehler:
        _fehler(vorschlag, str(fehler))
        raise JobAbbruch(str(fehler)) from fehler
    except ConnectorFehler as fehler:
        if not fehler.wiederholbar:
            _fehler(vorschlag, f"{fehler.meldung} ({fehler})")
            raise JobAbbruch(str(fehler)) from fehler
        if job.versuche + 1 >= job.max_versuche:
            _fehler(vorschlag, fehler.meldung)
        raise
    except Exception as fehler:
        if job.versuche + 1 >= job.max_versuche:
            _fehler(vorschlag, "Der Versand ist fehlgeschlagen. Bitte versuchen Sie es erneut.")
        log.exception("Versand fehlgeschlagen", extra={"vorschlag_id": vorschlag.pk})
        raise fehler
