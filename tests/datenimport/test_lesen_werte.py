"""M6-02/03: Excel und CSV einlesen, deutsche Formate deuten, Spalten zuordnen (H1, H2)."""

import io
import zipfile
from datetime import date, datetime
from decimal import Decimal

import pytest
from openpyxl import Workbook

from datenimport import werte
from datenimport.felder import FELDER, fehlende_pflichtfelder, vorlage_csv, vorlage_xlsx, vorschlagen
from datenimport.lesen import MAX_ZEILEN, LeseFehler, lesen


def _xlsx(zeilen, blaetter=("Tabelle1",)):
    mappe = Workbook()
    mappe.active.title = blaetter[0]
    for z in zeilen:
        mappe.active.append(z)
    for name in blaetter[1:]:
        mappe.create_sheet(name).append(["Nur", "Kopf"])
    puffer = io.BytesIO()
    mappe.save(puffer)
    return puffer.getvalue()


def test_xlsx_mit_zahlen_und_daten():
    daten = _xlsx(
        [
            ["Rechnungsnummer", "Datum", "Betrag", None],
            ["RE-1", datetime(2026, 9, 15), 1190.5, None],
            [None, None, None, None],
            ["RE-2", date(2026, 10, 2), 595, None],
        ],
        ("Offen", "Archiv"),
    )
    t = lesen("liste.xlsx", daten)
    assert t.blaetter == ["Offen", "Archiv"] and t.blatt == "Offen"
    assert t.spalten == ["Rechnungsnummer", "Datum", "Betrag"]
    assert t.zeilen == [["RE-1", "2026-09-15", "1190,5"], ["RE-2", "2026-10-02", "595"]]
    assert lesen("liste.xlsx", daten, blatt="Archiv").spalten == ["Nur", "Kopf"]


def test_csv_semikolon_cp1252_und_bom():
    text = "Name;Straße;Betrag\nMüller GmbH;Hauptstraße 1;1.234,56\n\n"
    assert lesen("a.csv", text.encode("cp1252")).zeilen == [["Müller GmbH", "Hauptstraße 1", "1.234,56"]]
    assert lesen("a.csv", ("﻿" + text).encode("utf-8")).spalten == ["Name", "Straße", "Betrag"]


def test_csv_komma_und_anfuehrungszeichen():
    t = lesen("a.csv", b'Name,Betrag\n"Bau AG, Niederlassung Nord","1,234.56"\n')
    assert t.zeilen == [["Bau AG, Niederlassung Nord", "1,234.56"]]


@pytest.mark.parametrize(
    ("daten", "meldung"),
    [
        (b"", "leer"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"x" * 100, ".xls"),
        (b"PK\x03\x04kaputt", "beschädigt"),
        (b"\x00\x01\x02bin", r"Excel-Datei \(\.xlsx\) oder CSV"),
        (b"\n\n;;\n", "leer"),
    ],
)
def test_ungueltige_dateien(daten, meldung):
    with pytest.raises(LeseFehler, match=meldung):
        lesen("x", daten)


def test_zip_ohne_arbeitsmappe_und_zip_bombe(monkeypatch):
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("nicht_excel.txt", "x")
    with pytest.raises(LeseFehler, match="keine Excel-Arbeitsmappe"):
        lesen("x.xlsx", puffer.getvalue())
    import datenimport.lesen as modul

    monkeypatch.setattr(modul, "MAX_ENTPACKT", 100)
    with pytest.raises(LeseFehler, match="entpackt zu groß"):
        lesen("x.xlsx", _xlsx([["A"], ["x" * 500]]))


def test_zu_viele_zeilen():
    text = "A\n" + "x\n" * (MAX_ZEILEN + 1)
    with pytest.raises(LeseFehler, match="Zu viele Zeilen"):
        lesen("a.csv", text.encode())


@pytest.mark.parametrize(
    ("text", "erwartet"),
    [
        ("1.234,56", "1234.56"),
        ("1234,5", "1234.5"),
        ("1,234.56", "1234.56"),
        ("1234.56", "1234.56"),
        ("1.234", "1234"),
        ("1.234.567", "1234567"),
        ("1,234,567", "1234567"),
        ("1 234,56 €", "1234.56"),
        ("-12,00", "-12.00"),
        ("(5,00)", "-5.00"),
        ("595", "595"),
        ("0,5", "0.5"),
    ],
)
def test_zahl(text, erwartet):
    assert werte.zahl(text) == Decimal(erwartet)


def test_betrag_rundet_kaufmaennisch():
    assert werte.betrag("10,005") == Decimal("10.01")
    with pytest.raises(werte.WertFehler):
        werte.zahl("zwölf")


@pytest.mark.parametrize(
    ("text", "erwartet"),
    [
        ("15.09.2026", date(2026, 9, 15)),
        ("5.9.26", date(2026, 9, 5)),
        ("2026-09-15", date(2026, 9, 15)),
        ("2026-09-15 00:00", date(2026, 9, 15)),
        ("46280", date(2026, 9, 15)),
    ],
)
def test_datum(text, erwartet):
    assert werte.datum(text) == erwartet


def test_datum_fehler():
    for text in ("31.02.2026", "09/15/2026", "morgen"):
        with pytest.raises(werte.WertFehler):
            werte.datum(text)


def test_steuersatz_nur_0_7_19():
    assert [werte.steuersatz(x) for x in ("19", "19 %", "0,19", "7", "0")] == [19, 19, 19, 7, 0]
    with pytest.raises(werte.WertFehler, match="nur 0, 7 oder 19"):
        werte.steuersatz("16")


def test_kundentyp_firma_artikeltyp_email():
    assert werte.kundentyp("Privatkunde") == "privat" and werte.kundentyp("gewerblich") == "unternehmer"
    assert werte.kundentyp("") is None
    with pytest.raises(werte.WertFehler):
        werte.kundentyp("vielleicht")
    assert werte.ist_firma("Huber Hausverwaltung GmbH") and werte.ist_firma("Meier & Co. KG")
    assert werte.ist_firma("Kita Sonnenschein e. V.") and not werte.ist_firma("Familie Weber")
    assert werte.ist_firma("Weber", art="Firma") and not werte.ist_firma("Bau AG", art="Person")
    assert werte.artikeltyp("Dienstleistung") == "SERVICE" and werte.artikeltyp("Material") == "PRODUCT"
    assert werte.email(" Info@Bau.example ") == "info@bau.example"
    with pytest.raises(werte.WertFehler):
        werte.email("keine-mail")


def test_vorschlaege_fuer_typische_excel_listen():
    spalten = ["Kd-Nr.", "Firma", "Vorname", "Nachname", "Straße", "PLZ", "Ort", "E-Mail", "Telefon"]
    z = vorschlagen("kunden", spalten)
    assert z == {
        "kundennummer": 0,
        "firma": 1,
        "vorname": 2,
        "nachname": 3,
        "strasse": 4,
        "plz": 5,
        "ort": 6,
        "email": 7,
        "telefon": 8,
    }
    z = vorschlagen("posten", ["Re-Nr.", "Datum", "Fälligkeit", "Kunde", "Betrag brutto", "Bezahlt"])
    assert z == {"rechnungsnummer": 0, "rechnungsdatum": 1, "faellig_am": 2, "kunde": 3, "betrag": 4, "bezahlt": 5}
    z = vorschlagen("artikel", ["Art.-Nr.", "Bezeichnung", "ME", "VK netto", "MwSt"])
    assert z == {"artikelnummer": 0, "bezeichnung": 1, "einheit": 2, "preis_netto": 3, "steuersatz": 4}


def test_pflichtfelder_und_eines_von():
    assert fehlende_pflichtfelder("kunden", {}) == ["Firma oder Name"]
    assert fehlende_pflichtfelder("kunden", {"nachname": 0}) == []
    assert "Preis netto oder Preis brutto" in fehlende_pflichtfelder("artikel", {"bezeichnung": 0, "einheit": 1})
    assert set(fehlende_pflichtfelder("posten", {})) == {"Rechnungsnummer", "Rechnungsdatum", "Kunde", "Betrag brutto"}


@pytest.mark.parametrize("art", ["kunden", "artikel", "posten"])
def test_vorlagen_werden_vollstaendig_zugeordnet(art):
    for datei in (vorlage_csv(art), vorlage_xlsx(art)):
        t = lesen("vorlage", datei)
        zuordnung = vorschlagen(art, t.spalten)
        assert len(zuordnung) == len(FELDER[art]), (art, t.spalten, zuordnung)
        assert len(t.zeilen) == 2
