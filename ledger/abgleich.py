"""Abgleich Bestandstool → Spiegel (B2, B3).

1. Erstimport: Kontakte, Artikel, offene und überfällige Rechnungen. Danach ist das Cockpit nutzbar.
   Die Zahlungshistorie der letzten 12 Monate (für die Zahlungsdauer, C3) folgt in einem eigenen Job.
2. Laufend: Webhooks laden einzelne Belege nach (M1-08).
3. Nachts: Voucherlist mit `updatedDateFrom` = letzter Abgleich minus 1 Tag, dazu die komplette
   Offen-Liste; jeder im Spiegel offene Beleg, der dort fehlt, wird einzeln nachgeladen.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from accounts.models import Firma
from connectors.base import AccountingConnector, Article, Contact, Receivable
from connectors.models import Verbindung

from .models import Artikel, Beleg, Kontakt

log = logging.getLogger(__name__)

HISTORIE_TAGE = 365


@dataclass
class Ergebnis:
    kontakte: int = 0
    artikel: int = 0
    belege: int = 0
    nachgeladen: int = 0
    offene_ids: set[str] = field(default_factory=set)


def kontakt_speichern(firma: Firma, kontakt: Contact) -> Kontakt:
    obj, _ = Kontakt.objects.update_or_create(
        firma=firma,
        extern_id=kontakt.extern_id,
        defaults={
            "name": kontakt.name[:250] or "(ohne Namen)",
            "email": kontakt.email,
            "kundennummer": kontakt.kundennummer,
            "ist_unternehmen_extern": kontakt.ist_unternehmen,
            "archiviert": kontakt.archiviert,
            "aktualisiert": timezone.now(),
        },
    )
    return obj


def kontakte_abgleichen(firma: Firma, kontakte: Iterable[Contact]) -> int:
    anzahl = 0
    for kontakt in kontakte:
        kontakt_speichern(firma, kontakt)
        anzahl += 1
    return anzahl


def artikel_abgleichen(firma: Firma, artikel: Iterable[Article]) -> int:
    anzahl = 0
    for a in artikel:
        Artikel.objects.update_or_create(
            firma=firma,
            extern_id=a.extern_id,
            defaults={
                "bezeichnung": a.bezeichnung[:250],
                "einheit": a.einheit,
                "netto": a.netto,
                "steuersatz": a.steuersatz,
                "typ": a.typ,
                "artikelnummer": a.artikelnummer,
                "archiviert": a.archiviert,
                "aktualisiert": timezone.now(),
            },
        )
        anzahl += 1
    return anzahl


def _kontakt_fuer(firma: Firma, posten: Receivable, connector: AccountingConnector | None) -> Kontakt | None:
    if not posten.kontakt_extern_id:
        return None  # Sammelkunde: ohne Kontakt kein Kundentyp, also nie automatisch mahnen
    kontakt = Kontakt.objects.fuer(firma).filter(extern_id=posten.kontakt_extern_id).first()
    if kontakt is None and connector is not None:
        geladen = connector.get_contact(posten.kontakt_extern_id)
        if geladen is not None:
            kontakt = kontakt_speichern(firma, geladen)
    if kontakt is None:
        kontakt = Kontakt.objects.create(
            firma=firma, extern_id=posten.kontakt_extern_id, name=posten.kontakt_name[:250] or "(unbekannt)"
        )
    return kontakt


def beleg_speichern(
    firma: Firma, posten: Receivable, connector: AccountingConnector | None = None, bezahlt_am: date | None = None
) -> Beleg:
    werte = {
        "art": posten.art,
        "nummer": posten.nummer,
        "belegdatum": posten.belegdatum,
        "faellig_am": posten.faellig_am,
        "kontakt": _kontakt_fuer(firma, posten, connector),
        "kontakt_name": posten.kontakt_name[:250],
        "brutto": posten.brutto,
        "offen": posten.offen,
        "status": posten.status,
        "aktualisiert_extern": posten.aktualisiert_extern,
        "zuletzt_abgeglichen": timezone.now(),
    }
    if bezahlt_am is not None:
        werte["bezahlt_am"] = bezahlt_am
    beleg, _ = Beleg.objects.update_or_create(firma=firma, extern_id=posten.extern_id, defaults=werte)
    return beleg


def _bezahlt_am_nachladen(firma: Firma, connector: AccountingConnector, beleg: Beleg) -> None:
    if beleg.status == Beleg.Status.BEZAHLT and beleg.bezahlt_am is None:
        status = connector.get_payment_status(beleg.extern_id)
        bezahlt_am = status.bezahlt_am or (max((d for d, _ in status.zahlungen if d), default=None))
        if bezahlt_am:
            Beleg.objects.filter(pk=beleg.pk).update(bezahlt_am=bezahlt_am)


def beleg_abgleichen(verbindung: Verbindung, connector: AccountingConnector, extern_id: str) -> Beleg | None:
    """Einzelnen Beleg nachladen (Webhook oder fehlend in der Offen-Liste). Nie dem Webhook-Payload vertrauen."""
    firma = verbindung.firma
    posten = connector.get_receivable(extern_id)
    if posten is None:
        # Gelöscht oder nicht mehr vorhanden: im Spiegel nicht mehr als offen führen
        Beleg.objects.fuer(firma).filter(extern_id=extern_id).update(
            status=Beleg.Status.STORNIERT, offen=0, zuletzt_abgeglichen=timezone.now()
        )
        return None
    beleg = beleg_speichern(firma, posten, connector)
    _bezahlt_am_nachladen(firma, connector, beleg)
    return beleg


def _offene_liste_abgleichen(verbindung: Verbindung, connector: AccountingConnector, ergebnis: Ergebnis) -> None:
    firma = verbindung.firma
    for posten in connector.list_open_receivables():
        beleg_speichern(firma, posten, connector)
        ergebnis.offene_ids.add(posten.extern_id)
        ergebnis.belege += 1
    # Im Spiegel offen, in Lexware nicht mehr in der Offen-Liste: einzeln nachladen
    verschwunden = (
        Beleg.objects.fuer(firma)
        .filter(status__in=Beleg.OFFENE_STATUS)
        .exclude(extern_id__in=ergebnis.offene_ids)
        .values_list("extern_id", flat=True)
    )
    for extern_id in list(verschwunden):
        beleg_abgleichen(verbindung, connector, extern_id)
        ergebnis.nachgeladen += 1


def erstimport(verbindung: Verbindung, connector: AccountingConnector) -> Ergebnis:
    firma = verbindung.firma
    ergebnis = Ergebnis()
    ergebnis.kontakte = kontakte_abgleichen(firma, connector.list_contacts())
    ergebnis.artikel = artikel_abgleichen(firma, connector.list_articles())
    with transaction.atomic():
        _offene_liste_abgleichen(verbindung, connector, ergebnis)
        jetzt = timezone.now()
        Verbindung.objects.filter(pk=verbindung.pk).update(letzter_abgleich=jetzt, erstimport_fertig=jetzt, fehler="")
    log.info("Erstimport fertig", extra={"firma_id": firma.pk, "belege": ergebnis.belege})
    return ergebnis


def zahlungshistorie(verbindung: Verbindung, connector: AccountingConnector, heute: date | None = None) -> int:
    """Bezahlte Rechnungen der letzten 12 Monate mit Zahldatum (für die Zahlungsdauer je Kunde, C3)."""
    firma = verbindung.firma
    heute = heute or timezone.localdate()
    anzahl = 0
    for posten in connector.list_receivables("paid,paidoff", heute - timedelta(days=HISTORIE_TAGE)):
        beleg = beleg_speichern(firma, posten, connector)
        _bezahlt_am_nachladen(firma, connector, beleg)
        anzahl += 1
    return anzahl


def nachtabgleich(verbindung: Verbindung, connector: AccountingConnector) -> Ergebnis:
    firma = verbindung.firma
    ergebnis = Ergebnis()
    ergebnis.kontakte = kontakte_abgleichen(firma, connector.list_contacts())
    ergebnis.artikel = artikel_abgleichen(firma, connector.list_articles())
    seit = (verbindung.letzter_abgleich or timezone.now()).astimezone(timezone.get_current_timezone()).date()
    for posten in connector.list_receivables("any", seit - timedelta(days=1)):
        if posten.status == "entwurf":
            continue
        beleg = beleg_speichern(firma, posten, connector)
        _bezahlt_am_nachladen(firma, connector, beleg)
        ergebnis.belege += 1
    _offene_liste_abgleichen(verbindung, connector, ergebnis)
    Verbindung.objects.filter(pk=verbindung.pk).update(letzter_abgleich=timezone.now(), fehler="")
    return ergebnis
