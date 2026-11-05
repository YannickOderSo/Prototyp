"""Excel (.xlsx) und CSV einlesen (H1).

Ergebnis ist immer Text je Zelle; gedeutet wird erst bei der Vorschau (werte.py). Zahlen aus Excel werden im
deutschen Format abgelegt (Dezimalkomma), Datumswerte als ISO-Datum, damit CSV und Excel gleich behandelt werden.

Schutz: höchstens 10 MB Datei, 50 MB entpackt (Zip-Bombe), 5.000 Zeilen, 50 Spalten. Alte .xls-Dateien und
alles andere werden mit verständlicher Meldung abgelehnt.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

MAX_BYTES = 10 * 1024 * 1024
MAX_ENTPACKT = 50 * 1024 * 1024
MAX_ZEILEN = 5000
MAX_SPALTEN = 50


class LeseFehler(Exception):
    """Datei lässt sich nicht lesen; die Meldung ist für den Nutzer gedacht."""


@dataclass
class Tabelle:
    blaetter: list[str]
    blatt: str
    spalten: list[str]
    zeilen: list[list[str]] = field(default_factory=list)


def _zelle(wert: object) -> str:
    if wert is None:
        return ""
    if isinstance(wert, bool):
        return "ja" if wert else "nein"
    if isinstance(wert, datetime):
        return wert.date().isoformat() if wert.time() == time(0, 0) else wert.isoformat(sep=" ", timespec="minutes")
    if isinstance(wert, date):
        return wert.isoformat()
    if isinstance(wert, int):
        return str(wert)
    if isinstance(wert, float | Decimal):
        text = format(Decimal(str(wert)).normalize(), "f")
        return text.replace(".", ",")
    return str(wert).strip()


def _aufbereiten(roh: list[list[str]], blaetter: list[str], blatt: str) -> Tabelle:
    zeilen = [z for z in roh if any(c.strip() for c in z)]
    if not zeilen:
        raise LeseFehler("Die Tabelle ist leer.")
    kopf = [c.strip() for c in zeilen[0]]
    while kopf and not kopf[-1]:
        kopf.pop()
    if len([k for k in kopf if k]) < 1:
        raise LeseFehler("Die erste Zeile enthält keine Spaltenüberschriften.")
    if len(kopf) > MAX_SPALTEN:
        raise LeseFehler(f"Zu viele Spalten (höchstens {MAX_SPALTEN}).")
    daten = []
    for zeile in zeilen[1:]:
        zeile = [c.strip() for c in zeile[: len(kopf)]]
        zeile += [""] * (len(kopf) - len(zeile))
        if any(zeile):
            daten.append(zeile)
    if len(daten) > MAX_ZEILEN:
        raise LeseFehler(f"Zu viele Zeilen (höchstens {MAX_ZEILEN}). Bitte die Datei aufteilen.")
    spalten = [k or f"Spalte {i + 1}" for i, k in enumerate(kopf)]
    return Tabelle(blaetter=blaetter, blatt=blatt, spalten=spalten, zeilen=daten)


def _xlsx(daten: bytes, blatt: str | None) -> Tabelle:
    try:
        with zipfile.ZipFile(io.BytesIO(daten)) as archiv:
            namen = archiv.namelist()
            if "xl/workbook.xml" not in namen:
                raise LeseFehler("Die Datei ist keine Excel-Arbeitsmappe (.xlsx).")
            if sum(i.file_size for i in archiv.infolist()) > MAX_ENTPACKT:
                raise LeseFehler("Die Excel-Datei ist entpackt zu groß.")
    except zipfile.BadZipFile as fehler:
        raise LeseFehler("Die Excel-Datei ist beschädigt.") from fehler
    from openpyxl import load_workbook

    try:
        mappe = load_workbook(io.BytesIO(daten), read_only=True, data_only=True)
    except Exception as fehler:  # openpyxl wirft je nach Defekt verschiedene Fehler
        raise LeseFehler("Die Excel-Datei lässt sich nicht öffnen.") from fehler
    try:
        blaetter = list(mappe.sheetnames)
        name = blatt if blatt and blatt in blaetter else blaetter[0]
        roh: list[list[str]] = []
        for zeile in mappe[name].iter_rows(values_only=True):
            roh.append([_zelle(w) for w in zeile[: MAX_SPALTEN + 1]])
            if len(roh) > MAX_ZEILEN + 50:
                break
    finally:
        mappe.close()
    return _aufbereiten(roh, blaetter, name)


def _csv(daten: bytes) -> Tabelle:
    for kodierung in ("utf-8-sig", "cp1252"):
        try:
            text = daten.decode(kodierung)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1252 dekodiert fast alles
        raise LeseFehler("Die Zeichenkodierung der CSV-Datei ist unbekannt.")
    erste = next((z for z in text.splitlines() if z.strip()), "")
    trenner = max((";", ",", "\t"), key=erste.count) if erste else ";"
    roh = [list(z) for z in csv.reader(io.StringIO(text), delimiter=trenner)]
    return _aufbereiten(roh, [], "")


def lesen(name: str, daten: bytes, blatt: str | None = None) -> Tabelle:
    if len(daten) > MAX_BYTES:
        raise LeseFehler("Die Datei ist größer als 10 MB.")
    if not daten.strip():
        raise LeseFehler("Die Datei ist leer.")
    if daten[:4] == b"PK\x03\x04":
        return _xlsx(daten, blatt)
    if daten[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise LeseFehler("Alte Excel-Dateien (.xls) bitte in Excel als .xlsx oder CSV speichern.")
    if b"\x00" in daten[:2048]:
        raise LeseFehler("Bitte eine Excel-Datei (.xlsx) oder CSV hochladen.")
    return _csv(daten)
