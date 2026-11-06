"""K6: Kontoauszüge lesen. camt.053 (Tagesauszug), camt.052 (Umsatzinformation) und CSV der Banken.

Regeln:
- Nur gebuchte Gutschriften (Zahlungseingänge) werden zurückgegeben. Abbuchungen, vorgemerkte Umsätze und
  Stornobuchungen werden schon hier verworfen und nirgends gespeichert.
- Sammelbuchungen mit mehreren Einzelumsätzen (TxDtls mit eigenem Betrag) werden aufgeteilt.
- IBANs werden gekürzt (DE89 •••• 3000); die volle IBAN wird nicht gespeichert.
- Jeder Umsatz bekommt einen Schlüssel gegen doppeltes Hochladen: Bankreferenz, sonst Datum, Betrag, Zahler und
  Verwendungszweck plus laufende Nummer gleicher Umsätze in der Datei (zwei gleiche Zahlungen am selben Tag
  bleiben zwei).
- XML nur mit abgesichertem Parser (keine DTD, keine Entitäten).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

MAX_BYTES = 10 * 1024 * 1024


class AuszugFehler(ValueError):
    pass


@dataclass
class Umsatz:
    buchungsdatum: date
    betrag: Decimal
    waehrung: str = "EUR"
    zahler: str = ""
    zahler_konto: str = ""
    verwendungszweck: str = ""
    referenz: str = ""
    schluessel: str = ""


@dataclass
class Auszug:
    format: str
    konto: str = ""
    von: date | None = None
    bis: date | None = None
    umsaetze: list[Umsatz] = field(default_factory=list)
    abbuchungen: int = 0
    vorgemerkt: int = 0


def iban_kurz(iban: str) -> str:
    iban = re.sub(r"\s+", "", iban or "").upper()
    if len(iban) < 10:
        return ""
    return f"{iban[:4]} •••• {iban[-4:]}"


def _betrag(text: str) -> Decimal | None:
    s = (text or "").strip().replace("€", "").replace("EUR", "").replace(" ", "").replace(" ", "")
    if not s:
        return None
    negativ = s.endswith("-") or s.startswith("-")
    s = s.strip("+-")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?|\d+,\d+|\d+", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?|\d+\.\d+", s):
        s = s.replace(",", "")
    else:
        return None
    try:
        wert = Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    return -wert if negativ else wert


def _datum(text: str) -> date | None:
    text = (text or "").strip()[:10]
    for muster in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, muster).date()
        except ValueError:
            continue
    return None


def _schluessel_setzen(konto: str, umsaetze: list[Umsatz]) -> None:
    gesehen: Counter[str] = Counter()
    for u in umsaetze:
        if u.referenz:
            basis = f"ref|{konto}|{u.referenz}|{u.buchungsdatum}|{u.betrag}"
        else:
            basis = f"inh|{konto}|{u.buchungsdatum}|{u.betrag}|{u.zahler.lower()}|{u.verwendungszweck.lower()}"
        gesehen[basis] += 1
        u.schluessel = hashlib.sha256(f"{basis}|{gesehen[basis]}".encode()).hexdigest()


def lesen(dateiname: str, daten: bytes) -> Auszug:
    if len(daten) > MAX_BYTES:
        raise AuszugFehler("Die Datei ist größer als 10 MB.")
    kopf = daten[:2000].lstrip(b"\xef\xbb\xbf").lstrip()
    if kopf.startswith(b"<"):
        auszug = _camt(daten)
    elif dateiname.lower().endswith((".csv", ".txt")) or b";" in kopf or b"," in kopf:
        auszug = _csv(daten)
    else:
        raise AuszugFehler("Unbekanntes Format. Bitte camt.053 (XML) oder CSV aus dem Online-Banking hochladen.")
    _schluessel_setzen(auszug.konto, auszug.umsaetze)
    return auszug


# ------------------------------------------------------------------ camt.053 / camt.052


def _lokal(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _kind(knoten: Any, *pfad: str) -> Any:
    for name in pfad:
        if knoten is None:
            return None
        knoten = next((k for k in knoten if _lokal(k.tag) == name), None)
    return knoten


def _kinder(knoten: Any, name: str) -> list[Any]:
    return [k for k in knoten if _lokal(k.tag) == name] if knoten is not None else []


def _text(knoten: Any, *pfad: str) -> str:
    k = _kind(knoten, *pfad)
    return (k.text or "").strip() if k is not None and k.text else ""


def _camt_datum(knoten: Any) -> date | None:
    return _datum(_text(knoten, "Dt") or _text(knoten, "DtTm"))


def _partei_name(knoten: Any) -> str:
    # bis Version 7: Dbtr/Nm, ab Version 8: Dbtr/Pty/Nm
    return _text(knoten, "Nm") or _text(knoten, "Pty", "Nm")


def _camt(daten: bytes) -> Auszug:
    from defusedxml import ElementTree
    from defusedxml.common import DefusedXmlException

    try:
        wurzel = ElementTree.fromstring(daten, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (DefusedXmlException, ElementTree.ParseError) as fehler:
        raise AuszugFehler("Die XML-Datei konnte nicht gelesen werden.") from fehler
    huelle = next(iter(wurzel), None)
    art = _lokal(huelle.tag) if huelle is not None else ""
    if art == "BkToCstmrStmt":
        auszug, berichte = Auszug("camt053"), _kinder(huelle, "Stmt")
    elif art == "BkToCstmrAcctRpt":
        auszug, berichte = Auszug("camt052"), _kinder(huelle, "Rpt")
    else:
        raise AuszugFehler("Das ist kein Kontoauszug im camt-Format (camt.053 oder camt.052).")
    alle_daten: list[date] = []
    for bericht in berichte:
        auszug.konto = auszug.konto or iban_kurz(_text(bericht, "Acct", "Id", "IBAN"))
        zeitraum = _kind(bericht, "FrToDt")
        if zeitraum is not None:
            for teil in ("FrDtTm", "ToDtTm"):
                d = _datum(_text(zeitraum, teil))
                if d:
                    alle_daten.append(d)
        for eintrag in _kinder(bericht, "Ntry"):
            buchung = _camt_datum(_kind(eintrag, "BookgDt")) or _camt_datum(_kind(eintrag, "ValDt"))
            if buchung:
                alle_daten.append(buchung)
            status = _text(eintrag, "Sts") or _text(eintrag, "Sts", "Cd")
            if status and status != "BOOK":
                auszug.vorgemerkt += 1
                continue
            if _text(eintrag, "CdtDbtInd") != "CRDT" or _text(eintrag, "RvslInd").lower() == "true":
                auszug.abbuchungen += 1
                continue
            if buchung is None:
                continue
            auszug.umsaetze.extend(_camt_umsaetze(eintrag, buchung))
    if alle_daten:
        auszug.von, auszug.bis = min(alle_daten), max(alle_daten)
    return auszug


def _camt_umsaetze(eintrag: Any, buchung: date) -> list[Umsatz]:
    amt = _kind(eintrag, "Amt")
    gesamt = _betrag((amt.text or "") if amt is not None else "")
    waehrung = (amt.get("Ccy") if amt is not None else "") or "EUR"
    bankref = _text(eintrag, "AcctSvcrRef")
    zusatz = _text(eintrag, "AddtlNtryInf")
    details = [tx for d in _kinder(eintrag, "NtryDtls") for tx in _kinder(d, "TxDtls")]
    umsaetze = []
    for i, tx in enumerate(details or [None]):
        betrag = gesamt
        if tx is not None and len(details) > 1:
            einzel = _kind(tx, "AmtDtls", "TxAmt", "Amt")
            if einzel is None:  # Elemente ohne Kinder sind „falsy“, daher kein `or`
                einzel = _kind(tx, "Amt")
            betrag = _betrag(einzel.text or "") if einzel is not None else None
        if betrag is None or betrag <= 0:
            continue
        rmt = _kind(tx, "RmtInf") if tx is not None else None
        zweck_teile = [k.text.strip() for k in _kinder(rmt, "Ustrd") if k.text]
        if rmt is not None:
            for strd in _kinder(rmt, "Strd"):
                ref = _text(strd, "CdtrRefInf", "Ref")
                if ref:
                    zweck_teile.append(ref)
        zweck = " ".join(zweck_teile) or zusatz
        parteien = _kind(tx, "RltdPties") if tx is not None else None
        e2e = _text(tx, "Refs", "EndToEndId") if tx is not None else ""
        referenz = _text(tx, "Refs", "AcctSvcrRef") if tx is not None else ""
        if not referenz and bankref:
            referenz = f"{bankref}/{i}" if len(details) > 1 else bankref
        if not referenz and e2e and e2e.upper() != "NOTPROVIDED":
            referenz = f"e2e:{e2e}"
        umsaetze.append(
            Umsatz(
                buchungsdatum=buchung,
                betrag=betrag,
                waehrung=waehrung.upper()[:3],
                zahler=(_partei_name(_kind(parteien, "Dbtr")) or _partei_name(_kind(parteien, "UltmtDbtr")))[:200],
                zahler_konto=iban_kurz(_text(parteien, "DbtrAcct", "Id", "IBAN")),
                verwendungszweck=re.sub(r"\s+", " ", zweck)[:500],
                referenz=referenz[:200],
            )
        )
    return umsaetze


# ------------------------------------------------------------------ CSV der Banken

SPALTEN: dict[str, list[str]] = {
    "datum": ["buchungstag", "buchungsdatum", "buchung", "datum", "buchungstag (datum)"],
    "valuta": ["valutadatum", "wertstellung", "wert", "valuta", "wertstellungsdatum"],
    "betrag": ["betrag", "betrag (€)", "betrag (eur)", "betrag in eur", "umsatz", "betrag in €"],
    "haben": ["haben", "gutschrift", "eingang"],
    "soll": ["soll", "lastschrift", "ausgang"],
    "zahler": [
        "beguenstigter/zahlungspflichtiger",
        "begünstigter/zahlungspflichtiger",
        "name zahlungsbeteiligter",
        "zahlungspflichtige*r",
        "auftraggeber/empfänger",
        "begünstigter / auftraggeber",
        "auftraggeber / begünstigter",
        "zahlungspflichtiger",
        "auftraggeber",
        "gegenpartei",
        "name",
    ],
    "iban": ["kontonummer/iban", "iban zahlungsbeteiligter", "iban", "iban gegenkonto", "auftraggeberkonto"],
    "zweck": ["verwendungszweck", "buchungsdetails", "beschreibung", "verwendungszweck/ buchungstext"],
    "waehrung": ["waehrung", "währung"],
    "referenz": ["kundenreferenz (end-to-end)", "kundenreferenz", "end-to-end-referenz"],
    "konto": ["auftragskonto", "iban auftragskonto"],
    "status": ["status", "info"],
}


def _e2e(referenz: str) -> str:
    return "" if referenz.upper() in ("", "NOTPROVIDED") else f"e2e:{referenz}"[:200]


def _dekodieren(daten: bytes) -> str:
    try:
        return daten.decode("utf-8-sig")
    except UnicodeDecodeError:
        return daten.decode("cp1252", errors="replace")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().strip('"').lower())


def _kopfzeile(zeilen: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    """Sucht in den ersten 30 Zeilen die Kopfzeile (Banken setzen oft Kontoinfos davor)."""
    for nr, zeile in enumerate(zeilen[:30]):
        namen = [_norm(z) for z in zeile]
        spalten: dict[str, int] = {}
        for schluessel, synonyme in SPALTEN.items():
            for syn in synonyme:  # Reihenfolge der Synonyme = Vorrang
                if syn in namen:
                    spalten[schluessel] = namen.index(syn)
                    break
        if "datum" in spalten and ("betrag" in spalten or "haben" in spalten):
            return nr, spalten
    return None


def _csv(daten: bytes) -> Auszug:
    text = _dekodieren(daten)
    erste = next((z for z in text.splitlines() if z.strip()), "")
    trenner = max([";", ",", "\t"], key=lambda t: text[:5000].count(t)) if erste else ";"
    zeilen = list(csv.reader(io.StringIO(text), delimiter=trenner))
    kopf = _kopfzeile(zeilen)
    if kopf is None:
        raise AuszugFehler(
            "In der CSV-Datei fehlen die Spalten Buchungstag und Betrag. "
            "Bitte den Umsatz-Export Ihrer Bank im CSV-Format nutzen."
        )
    start, sp = kopf
    auszug = Auszug("csv")
    vorspann = " ".join(";".join(z) for z in zeilen[:start])
    treffer = re.search(r"\b([A-Z]{2}\d{2}(?:\s?[0-9A-Z]{4}){3,7}(?:\s?[0-9A-Z]{1,4})?)\b", vorspann)
    if treffer:
        auszug.konto = iban_kurz(treffer.group(1))

    def wert(zeile: list[str], name: str) -> str:
        i = sp.get(name)
        return zeile[i].strip() if i is not None and i < len(zeile) else ""

    daten_liste: list[date] = []
    for zeile in zeilen[start + 1 :]:
        if not any(z.strip() for z in zeile):
            continue
        buchung = _datum(wert(zeile, "datum")) or _datum(wert(zeile, "valuta"))
        if buchung is None:
            continue
        daten_liste.append(buchung)
        if not auszug.konto and wert(zeile, "konto"):
            auszug.konto = iban_kurz(wert(zeile, "konto"))
        status = _norm(wert(zeile, "status"))
        if "vorgemerkt" in status or "vormerkung" in status or status == "pending":
            auszug.vorgemerkt += 1
            continue
        if "haben" in sp:  # getrennte Spalten Soll und Haben (z. B. Deutsche Bank)
            betrag = _betrag(wert(zeile, "haben"))
            if betrag is None or betrag == 0:
                betrag = -(abs(_betrag(wert(zeile, "soll")) or Decimal("0")))
        else:
            betrag = _betrag(wert(zeile, "betrag"))
        if betrag is None or betrag <= 0:
            auszug.abbuchungen += 1
            continue
        auszug.umsaetze.append(
            Umsatz(
                buchungsdatum=buchung,
                betrag=betrag,
                waehrung=(wert(zeile, "waehrung") or "EUR").upper()[:3],
                zahler=wert(zeile, "zahler")[:200],
                zahler_konto=iban_kurz(wert(zeile, "iban")),
                verwendungszweck=re.sub(r"\s+", " ", wert(zeile, "zweck"))[:500],
                referenz=_e2e(wert(zeile, "referenz")),
            )
        )
    if daten_liste:
        auszug.von, auszug.bis = min(daten_liste), max(daten_liste)
    return auszug
