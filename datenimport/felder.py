"""Felder je Importart, Vorschläge für die Spaltenzuordnung und Vorlagen zum Herunterladen (H2)."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Feld:
    schluessel: str
    titel: str
    pflicht: bool
    synonyme: tuple[str, ...]
    beispiel: tuple[str, str]


FELDER: dict[str, list[Feld]] = {
    "kunden": [
        Feld("firma", "Firma", False, ("firma", "firmenname", "unternehmen", "firma name", "name1"), ("Bau AG", "")),
        Feld(
            "nachname",
            "Name",
            False,
            ("name", "nachname", "kunde", "kundenname", "name2", "ansprechpartner"),
            ("", "Musterfrau"),
        ),
        Feld("vorname", "Vorname", False, ("vorname", "firstname"), ("", "Erika")),
        Feld("art", "Firma oder Person", False, ("art", "kundenart", "firma person", "typ"), ("Firma", "Person")),
        Feld(
            "email",
            "E-Mail",
            False,
            ("email", "e mail", "mail", "e mail adresse", "emailadresse"),
            ("buchhaltung@bau-ag.example", "erika@example.org"),
        ),
        Feld(
            "strasse",
            "Straße",
            False,
            ("strasse", "str", "strasse hausnummer", "anschrift", "adresse"),
            ("Hauptstraße 1", "Gartenweg 5"),
        ),
        Feld("plz", "PLZ", False, ("plz", "postleitzahl"), ("12345", "54321")),
        Feld("ort", "Ort", False, ("ort", "stadt", "wohnort"), ("Musterstadt", "Beispieldorf")),
        Feld("land", "Land", False, ("land", "laendercode", "country"), ("DE", "DE")),
        Feld(
            "telefon",
            "Telefon",
            False,
            ("telefon", "tel", "telefonnummer", "handy", "mobil", "telefon mobil"),
            ("0123 456789", ""),
        ),
        Feld(
            "kundennummer",
            "Kundennummer",
            False,
            ("kundennummer", "kunden nr", "kundennr", "kd nr", "kdnr", "nr"),
            ("K-1001", "K-1002"),
        ),
        Feld(
            "kundentyp",
            "Kundentyp",
            False,
            ("kundentyp", "privat gewerblich", "gewerblich", "b2b b2c"),
            ("Unternehmer", "Privat"),
        ),
    ],
    "artikel": [
        Feld(
            "bezeichnung",
            "Bezeichnung",
            True,
            ("bezeichnung", "artikel", "leistung", "beschreibung", "name", "titel", "artikelbezeichnung", "position"),
            ("Malerarbeiten Facharbeiter", "Dispersionsfarbe weiß 12,5 l"),
        ),
        Feld(
            "artikelnummer",
            "Artikelnummer",
            False,
            ("artikelnummer", "artikel nr", "art nr", "artnr", "nummer", "nr", "sku"),
            ("M-100", "F-200"),
        ),
        Feld("einheit", "Einheit", True, ("einheit", "me", "mengeneinheit", "unit"), ("Stunde", "Eimer")),
        Feld(
            "preis_netto",
            "Preis netto",
            False,
            ("preis netto", "nettopreis", "netto", "preis", "ek", "vk", "einzelpreis", "preis ohne mwst", "vk netto"),
            ("58,00", "64,90"),
        ),
        Feld(
            "preis_brutto",
            "Preis brutto",
            False,
            ("preis brutto", "bruttopreis", "brutto", "preis inkl mwst", "vk brutto"),
            ("", ""),
        ),
        Feld(
            "steuersatz",
            "Steuersatz",
            False,
            ("steuersatz", "mwst", "ust", "mwst satz", "umsatzsteuer", "steuer"),
            ("19", "19"),
        ),
        Feld("typ", "Art", False, ("art", "typ", "kategorie", "artikelart"), ("Dienstleistung", "Material")),
    ],
    "posten": [
        Feld(
            "rechnungsnummer",
            "Rechnungsnummer",
            True,
            ("rechnungsnummer", "rechnung", "re nr", "rechnungsnr", "renr", "belegnummer", "beleg", "nr", "nummer"),
            ("RE-2026-041", "RE-2026-044"),
        ),
        Feld(
            "rechnungsdatum",
            "Rechnungsdatum",
            True,
            ("rechnungsdatum", "datum", "belegdatum", "re datum"),
            ("15.09.2026", "02.10.2026"),
        ),
        Feld(
            "faellig_am",
            "Fällig am",
            False,
            ("faellig am", "faelligkeit", "faellig", "zahlungsziel", "faelligkeitsdatum"),
            ("29.09.2026", "16.10.2026"),
        ),
        Feld(
            "kunde",
            "Kunde",
            True,
            ("kunde", "kundenname", "name", "firma", "empfaenger", "rechnungsempfaenger"),
            ("Bau AG", "Erika Musterfrau"),
        ),
        Feld(
            "kundennummer",
            "Kundennummer",
            False,
            ("kundennummer", "kunden nr", "kundennr", "kd nr", "kdnr"),
            ("K-1001", "K-1002"),
        ),
        Feld(
            "betrag",
            "Betrag brutto",
            True,
            ("betrag brutto", "brutto", "betrag", "rechnungsbetrag", "summe", "gesamt", "gesamtbetrag", "endbetrag"),
            ("1.190,00", "595,00"),
        ),
        Feld(
            "bezahlt",
            "Bereits bezahlt",
            False,
            ("bezahlt", "bereits bezahlt", "gezahlt", "anzahlung", "teilzahlung"),
            ("0,00", "100,00"),
        ),
        Feld("offen", "Offen", False, ("offen", "offener betrag", "restbetrag", "rest", "noch offen"), ("", "")),
    ],
}


def _normal(text: str) -> str:
    text = text.lower().replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def vorschlagen(art: str, spalten: list[str]) -> dict[str, int]:
    """Feld → Spaltennummer. Erst exakte Treffer der Synonyme, dann Teiltreffer; jede Spalte höchstens einmal."""
    normal = [_normal(s) for s in spalten]
    zuordnung: dict[str, int] = {}
    belegt: set[int] = set()
    for runde in ("exakt", "teil"):
        for feld in FELDER[art]:
            if feld.schluessel in zuordnung:
                continue
            for synonym in (feld.titel.lower(), *feld.synonyme):
                s = _normal(synonym)
                for i, spalte in enumerate(normal):
                    if i in belegt or not spalte:
                        continue
                    passt = (
                        spalte == s
                        if runde == "exakt"
                        else (len(s) > 3 and (s in spalte.split() or spalte.startswith(s)))
                    )
                    if passt:
                        zuordnung[feld.schluessel] = i
                        belegt.add(i)
                        break
                if feld.schluessel in zuordnung:
                    break
    return zuordnung


# Mindestens eines dieser Felder muss zugeordnet sein
EINES_VON: dict[str, list[tuple[str, ...]]] = {
    "kunden": [("firma", "nachname")],
    "artikel": [("preis_netto", "preis_brutto")],
    "posten": [],
}


def titel(art: str, schluessel: str) -> str:
    return next(f.titel for f in FELDER[art] if f.schluessel == schluessel)


def fehlende_pflichtfelder(art: str, zuordnung: dict[str, int]) -> list[str]:
    fehlend = [f.titel for f in FELDER[art] if f.pflicht and f.schluessel not in zuordnung]
    for gruppe in EINES_VON[art]:
        if not any(g in zuordnung for g in gruppe):
            fehlend.append(" oder ".join(titel(art, g) for g in gruppe))
    return fehlend


def vorlage_csv(art: str) -> bytes:
    puffer = io.StringIO()
    schreiber = csv.writer(puffer, delimiter=";")
    schreiber.writerow([f.titel for f in FELDER[art]])
    for i in (0, 1):
        schreiber.writerow([f.beispiel[i] for f in FELDER[art]])
    return ("﻿" + puffer.getvalue()).encode("utf-8")


def vorlage_xlsx(art: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    mappe = Workbook()
    blatt = mappe.active
    assert blatt is not None
    blatt.title = {"kunden": "Kunden", "artikel": "Artikel", "posten": "Offene Rechnungen"}[art]
    blatt.append([f.titel for f in FELDER[art]])
    for zelle in blatt[1]:
        zelle.font = Font(bold=True)
    for i in (0, 1):
        blatt.append([f.beispiel[i] for f in FELDER[art]])
    for spalte, feld in zip(blatt.columns, FELDER[art], strict=False):
        blatt.column_dimensions[spalte[0].column_letter].width = max(14, len(feld.titel) + 4)
    puffer = io.BytesIO()
    mappe.save(puffer)
    return puffer.getvalue()
