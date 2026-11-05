"""Zellen deuten: Beträge, Daten, Steuersätze, Kundentyp (H1). Jede Funktion wirft WertFehler mit deutscher Meldung."""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

CENT = Decimal("0.01")


class WertFehler(ValueError):
    pass


def zahl(text: str) -> Decimal:
    """Deutsches oder englisches Zahlenformat, mit Tausenderpunkten, Euro-Zeichen und Leerzeichen.

    Mehrdeutig ist nur „1.234“: Ein einzelner Punkt mit genau drei Ziffern danach gilt als Tausenderpunkt.
    """
    roh = text.strip().replace("€", "").replace("EUR", "").replace(" ", "").replace(" ", "").replace("'", "")
    if not roh:
        raise WertFehler("leer")
    negativ = roh.startswith("-") or (roh.startswith("(") and roh.endswith(")"))
    roh = roh.strip("-()+")
    if "," in roh and "." in roh:
        dezimal = "," if roh.rfind(",") > roh.rfind(".") else "."
        tausender = "." if dezimal == "," else ","
        roh = roh.replace(tausender, "").replace(dezimal, ".")
    elif "," in roh:
        # Ein Komma = Dezimalkomma (deutsches Format); mehrere Kommas = englische Tausendertrennung
        roh = roh.replace(",", "") if roh.count(",") > 1 else roh.replace(",", ".")
    elif roh.count(".") > 1 or (roh.count(".") == 1 and len(roh.split(".")[1]) == 3):
        roh = roh.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d+)?", roh):
        raise WertFehler(f"„{text}“ ist keine Zahl")
    try:
        wert = Decimal(roh)
    except InvalidOperation as fehler:  # pragma: no cover - durch das Muster ausgeschlossen
        raise WertFehler(f"„{text}“ ist keine Zahl") from fehler
    return -wert if negativ else wert


def betrag(text: str) -> Decimal:
    return zahl(text).quantize(CENT, rounding=ROUND_HALF_UP)


_EXCEL_NULL = date(1899, 12, 30)


def datum(text: str) -> date:
    roh = text.strip()
    if not roh:
        raise WertFehler("leer")
    treffer = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?", roh)
    if treffer:
        j, m, t = (int(x) for x in treffer.groups())
    else:
        treffer = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})", roh)
        if treffer:
            t, m, j = (int(x) for x in treffer.groups())
            if j < 100:
                j += 2000 if j < 70 else 1900
        elif re.fullmatch(r"\d{5}", roh) and 20000 <= int(roh) <= 80000:
            return _EXCEL_NULL + timedelta(days=int(roh))  # Excel-Seriennummer aus einer CSV
        else:
            raise WertFehler(f"„{text}“ ist kein Datum (erwartet TT.MM.JJJJ)")
    try:
        return date(j, m, t)
    except ValueError as fehler:
        raise WertFehler(f"„{text}“ ist kein gültiges Datum") from fehler


def steuersatz(text: str) -> Decimal:
    """Nur die in Lexware erlaubten Sätze 0, 7 und 19 Prozent (Doku, Stand März 2024)."""
    roh = text.strip().replace("%", "").replace(" ", "")
    if not roh:
        raise WertFehler("leer")
    wert = zahl(roh)
    if Decimal(0) < wert < 1:
        wert = wert * 100  # 0,19 → 19
    wert = wert.normalize()
    if wert not in (Decimal(0), Decimal(7), Decimal(19)):
        raise WertFehler(f"Steuersatz „{text}“ ist nicht erlaubt (nur 0, 7 oder 19 %)")
    return Decimal(int(wert))


def kundentyp(text: str) -> str | None:
    roh = text.strip().lower()
    if not roh:
        return None
    if roh in {"privat", "privatkunde", "privatperson", "p", "verbraucher", "b2c", "endkunde"}:
        return "privat"
    if roh in {
        "unternehmer",
        "unternehmen",
        "firma",
        "gewerblich",
        "gewerbe",
        "geschäftskunde",
        "geschaeftskunde",
        "b2b",
        "u",
        "g",
        "firmenkunde",
    }:
        return "unternehmer"
    raise WertFehler(f"Kundentyp „{text}“ unbekannt (Privat oder Unternehmer)")


_RECHTSFORM = re.compile(
    r"\b(gmbh|ag|kg|ug|ohg|gbr|mbh|e\.\s?k\.|e\.\s?v\.|eg|se|partg|ltd|inc|co\.)(\b|$)|&\s*co", re.IGNORECASE
)


def ist_firma(name: str, art: str = "") -> bool:
    """Firma oder Person: ausdrückliche Angabe zuerst, sonst Rechtsform im Namen."""
    roh = art.strip().lower()
    if roh in {"firma", "unternehmen", "gewerbe", "gewerblich", "b2b", "company", "f"}:
        return True
    if roh in {"person", "privat", "privatperson", "p"}:
        return False
    return bool(_RECHTSFORM.search(name))


def artikeltyp(text: str) -> str | None:
    roh = text.strip().lower()
    if not roh:
        return None
    if roh in {"dienstleistung", "service", "leistung", "lohn", "arbeit", "arbeitszeit", "d"}:
        return "SERVICE"
    if roh in {"produkt", "material", "ware", "artikel", "product", "p", "m"}:
        return "PRODUCT"
    raise WertFehler(f"Art „{text}“ unbekannt (Dienstleistung oder Material)")


def email(text: str) -> str:
    roh = text.strip()
    if not roh:
        return ""
    try:
        validate_email(roh)
    except ValidationError as fehler:
        raise WertFehler(f"„{text}“ ist keine gültige E-Mail-Adresse") from fehler
    return roh.lower()
