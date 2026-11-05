"""Freigabe einer Erfassung und Übertragung als Entwurf ins Bestandstool (E7, B5, ADR-004).

Es entsteht immer nur ein ENTWURF (ohne finalize). Rechnungsnummer, Steuerausweis, E-Rechnung und Archiv
entstehen erst, wenn der Nutzer den Entwurf in Lexware abschließt (ADR-001).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from accounts.models import Nutzer
from audit.services import protokolliere
from connectors.base import DraftLine, ExternalRef, InvoiceDraft, QuotationDraft
from connectors.services import aktive_verbindung, connector_fuer
from jobs.models import Job
from jobs.queue import enqueue

from .entwurf import regeln_anwenden
from .models import Erfassung

ANGEBOT_GUELTIG_TAGE = 30


def freigeben(erfassung: Erfassung, nutzer: Nutzer) -> Job:
    """Prüft erneut mit den Regeln und gibt frei. Wirft ValueError, wenn Blocker bestehen."""
    with transaction.atomic():
        erfassung = Erfassung.objects.select_for_update().get(pk=erfassung.pk)
        if erfassung.status != Erfassung.Status.PRUEFUNG:
            raise ValueError("Diese Erfassung ist nicht zur Freigabe bereit.")
        entwurf = regeln_anwenden(erfassung)
        if not entwurf.freigabefaehig:
            raise ValueError("Der Entwurf hat noch offene Punkte und kann nicht freigegeben werden.")
        if aktive_verbindung(erfassung.firma) is None:
            raise ValueError("Es besteht keine Verbindung zu Lexware.")
        erfassung.status = Erfassung.Status.FREIGEGEBEN
        erfassung.freigegeben_von = nutzer
        erfassung.freigegeben_am = timezone.now()
        erfassung.fehler = ""
        erfassung.save(update_fields=["status", "freigegeben_von", "freigegeben_am", "fehler"])
        protokolliere(
            erfassung.firma,
            "erfassung.freigegeben",
            nutzer=nutzer,
            objekt=erfassung,
            daten={"belegart": entwurf.belegart, "netto": str(entwurf.summen()["netto"])},
        )
        return enqueue(
            "capture.uebertragen",
            {"erfassung_id": erfassung.pk},
            firma=erfassung.firma,
            eindeutig=f"uebertragen:{erfassung.pk}",
        )


def _datum(text: Any) -> date | None:
    return date.fromisoformat(str(text)) if text else None


def _positionen(entwurf: dict[str, Any]) -> tuple[DraftLine, ...]:
    positionen = []
    for p in entwurf["positionen"]:
        if p.get("netto") is None or p.get("steuersatz") is None:
            raise ValueError("Position ohne Preis: Übertragung abgebrochen.")
        positionen.append(
            DraftLine(
                name=str(p["beschreibung"]),
                menge=Decimal(str(p["menge"])),
                einheit=str(p.get("einheit") or ""),
                netto=Decimal(str(p["netto"])),
                steuersatz=Decimal(str(p["steuersatz"])),
                artikel_extern_id=p.get("artikel_id") or None,
                artikel_typ=(p.get("artikel_typ") or None) if p.get("artikel_id") else None,
            )
        )
    return tuple(positionen)


def uebertragen(erfassung: Erfassung) -> ExternalRef | None:
    if erfassung.status != Erfassung.Status.FREIGEGEBEN or erfassung.ziel_extern_id:
        return None
    verbindung = aktive_verbindung(erfassung.firma)
    if verbindung is None:
        raise ValueError("Es besteht keine Verbindung zu Lexware.")
    entwurf = erfassung.entwurf
    heute = timezone.localdate()
    connector = connector_fuer(verbindung)
    if entwurf["belegart"] == "angebot":
        ref = connector.create_quotation_draft(
            QuotationDraft(
                kontakt_extern_id=entwurf["kunde_extern_id"],
                belegdatum=heute,
                gueltig_bis=heute + timedelta(days=ANGEBOT_GUELTIG_TAGE),
                positionen=_positionen(entwurf),
                steuerart=entwurf.get("steuerart") or "net",
            )
        )
    else:
        ref = connector.create_invoice_draft(
            InvoiceDraft(
                kontakt_extern_id=entwurf["kunde_extern_id"],
                belegdatum=heute,
                positionen=_positionen(entwurf),
                leistung_von=_datum(entwurf.get("leistung_von")),
                leistung_bis=_datum(entwurf.get("leistung_bis")),
                steuerart=entwurf.get("steuerart") or "net",
            )
        )
    erfassung.ziel_art = ref.art
    erfassung.ziel_extern_id = ref.extern_id
    erfassung.ziel_url = ref.url
    erfassung.status = Erfassung.Status.UEBERTRAGEN
    erfassung.save(update_fields=["ziel_art", "ziel_extern_id", "ziel_url", "status"])
    protokolliere(
        erfassung.firma,
        "lexware.entwurf_angelegt",
        nutzer=erfassung.freigegeben_von,
        objekt=erfassung,
        daten={"art": ref.art, "id": ref.extern_id},
    )
    return ref


def zurueck_zur_pruefung(erfassung: Erfassung, meldung: str) -> None:
    Erfassung.objects.filter(pk=erfassung.pk).update(
        status=Erfassung.Status.PRUEFUNG, fehler=meldung[:2000], freigegeben_von=None, freigegeben_am=None
    )
    protokolliere(
        erfassung.firma, "erfassung.uebertragung_fehlgeschlagen", objekt=erfassung, daten={"fehler": meldung[:300]}
    )
