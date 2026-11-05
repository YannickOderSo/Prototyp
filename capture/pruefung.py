"""Prüfansicht (E6): Änderungen des Nutzers in die Eingabe der Regeln übernehmen und neu prüfen."""

from __future__ import annotations

from typing import Any

from django.http import QueryDict

from accounts.models import Nutzer
from audit.services import protokolliere
from ledger.models import Artikel, Kontakt

from .entwurf import regeln_anwenden
from .models import Erfassung
from .rules import HERKUNFT_TEXT

MAX_POSITIONEN = 100


def _position_aus_formular(daten: QueryDict, praefix: str, herkunft: str, quelle: str) -> dict[str, Any]:
    return {
        "artikel_id": daten.get(f"{praefix}-artikel_id", "").strip(),
        "beschreibung": daten.get(f"{praefix}-beschreibung", "").strip()[:255],
        "menge": daten.get(f"{praefix}-menge", "").strip().replace(",", "."),
        "einheit": daten.get(f"{praefix}-einheit", "").strip()[:50],
        "quelle": quelle,
        "herkunft": herkunft,
        "preis_nutzer": daten.get(f"{praefix}-preis_nutzer", "").strip().replace(",", "."),
        "steuersatz_nutzer": daten.get(f"{praefix}-steuersatz_nutzer", "").strip(),
    }


def aenderungen_uebernehmen(erfassung: Erfassung, nutzer: Nutzer, daten: QueryDict) -> None:
    if erfassung.status != Erfassung.Status.PRUEFUNG:
        raise ValueError("Der Entwurf kann nicht mehr bearbeitet werden.")
    alt = erfassung.eingabe or dict(erfassung.ki_ergebnis)
    alte_positionen = list(alt.get("positionen") or [])
    positionen = []
    for i, bisher in enumerate(alte_positionen[:MAX_POSITIONEN]):
        if daten.get(f"pos-{i}-entfernen"):
            continue
        positionen.append(
            _position_aus_formular(
                daten, f"pos-{i}", str(bisher.get("herkunft", "notiz")), str(bisher.get("quelle", ""))
            )
        )
    if daten.get("neu-beschreibung", "").strip() and len(positionen) < MAX_POSITIONEN:
        positionen.append(_position_aus_formular(daten, "neu", "nutzer", "Prüfansicht"))
    kunde = Kontakt.objects.fuer(erfassung.firma).filter(extern_id=daten.get("kunde", "")).first()
    erfassung.eingabe = {
        **alt,
        "belegart": daten.get("belegart", alt.get("belegart", "unklar")),
        "kunde": kunde.name if kunde else alt.get("kunde", ""),
        "angebot_nummer": daten.get("angebot_nummer", "").strip()[:50],
        "leistung_von": daten.get("leistung_von", "").strip(),
        "leistung_bis": daten.get("leistung_bis", "").strip(),
        "positionen": positionen,
    }
    erfassung.save(update_fields=["eingabe"])
    regeln_anwenden(erfassung)
    protokolliere(erfassung.firma, "erfassung.entwurf_bearbeitet", nutzer=nutzer, objekt=erfassung)


def ansicht(erfassung: Erfassung) -> dict[str, Any]:
    """Daten für die Prüfansicht: Positionen mit Herkunftstexten, Auswahl an Kunden und Artikeln."""
    eingabe = erfassung.eingabe or erfassung.ki_ergebnis
    roh_positionen = list(eingabe.get("positionen") or [])
    positionen = []
    for i, p in enumerate(erfassung.entwurf.get("positionen", [])):
        roh = roh_positionen[i] if i < len(roh_positionen) else {}
        positionen.append(
            {
                **p,
                "index": i,
                "herkunft_text": HERKUNFT_TEXT.get(str(p.get("herkunft", "")), "aus Notiz"),
                "preis_nutzer": roh.get("preis_nutzer", ""),
                "steuersatz_nutzer": roh.get("steuersatz_nutzer", ""),
            }
        )
    return {
        "positionen": positionen,
        "kunden": Kontakt.objects.fuer(erfassung.firma).filter(archiviert=False).order_by("name"),
        "artikel": Artikel.objects.fuer(erfassung.firma).filter(archiviert=False).order_by("bezeichnung"),
        "steuersaetze": ["19", "7", "0"],
    }
