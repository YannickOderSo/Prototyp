"""M9-02: E-Rechnungen lesen – ZUGFeRD/Factur-X, XRechnung CII und UBL, sicher und mit gleichen Werten (K2)."""

from datetime import date
from decimal import Decimal

import pytest

from quellen.erechnung import ERechnungFehler, KeineERechnung, faelligkeit_aus_text, lesen
from tests.quellen.hilfen import datei, pdf_ohne_xml, zugferd_pdf

ERWARTET = {
    "nummer": "RE-2026-0412",
    "art": "rechnung",
    "belegdatum": date(2026, 10, 20),
    "faellig_am": date(2026, 11, 3),
    "waehrung": "EUR",
    "verkaeufer": "Malerbetrieb Muster GmbH",
    "verkaeufer_ustid": "DE123456789",
    "brutto": Decimal("2142.00"),
    "vorauszahlung": Decimal("500.00"),
    "zahlbetrag": Decimal("1642.00"),
}


@pytest.mark.parametrize(
    ("name", "inhalt", "format_name"),
    [
        ("rechnung.xml", datei("xrechnung_cii.xml"), "xrechnung_cii"),
        ("rechnung.xml", datei("xrechnung_ubl.xml"), "xrechnung_ubl"),
        ("rechnung.pdf", zugferd_pdf(datei("xrechnung_cii.xml")), "zugferd"),
        ("rechnung.pdf", zugferd_pdf(datei("xrechnung_cii.xml"), name="ZUGFeRD-invoice.xml"), "zugferd"),
    ],
)
def test_alle_formate_ergeben_dieselben_werte(name, inhalt, format_name):
    r = lesen(name, inhalt)
    assert r.format == format_name
    for feld, wert in ERWARTET.items():
        assert getattr(r, feld) == wert, feld
    assert r.faelligkeit_aus == "BT-9"
    assert r.kaeufer.name == "Huber Hausverwaltung GmbH"
    assert r.kaeufer.email == "rechnung@huber-hv.example"
    assert r.kaeufer.ustid == "DE987654321"
    assert r.kaeufer.anschrift == "Huber Hausverwaltung GmbH\nLindenallee 4\n12345 Musterstadt"
    daten = r.als_dict()
    assert daten["zahlbetrag"] == "1642.00" and daten["faellig_am"] == "2026-11-03" and daten["art"] == "rechnung"


def test_gutschrift_mit_bezug():
    r = lesen("gs.xml", datei("gutschrift_ubl.xml"))
    assert (r.art, r.nummer, r.bezug, r.zahlbetrag) == ("gutschrift", "GS-2026-007", "RE-2026-0412", Decimal("238.00"))
    assert r.faellig_am is None


def test_dtd_und_entitaeten_werden_abgelehnt():
    with pytest.raises(ERechnungFehler, match="Sicherheitsgründen"):
        lesen("angriff.xml", datei("angriff_dtd.xml"))


def test_keine_erechnung():
    with pytest.raises(KeineERechnung, match="keine eingebetteten Rechnungsdaten"):
        lesen("scan.pdf", pdf_ohne_xml())
    with pytest.raises(KeineERechnung, match="weder PDF noch XML"):
        lesen("foto.jpg", b"\xff\xd8\xff\xe0 kein Text")
    with pytest.raises(KeineERechnung, match="keine Rechnung"):
        lesen("andere.xml", b"<?xml version='1.0'?><Bestellung/>")


def test_fehlerhafte_dateien():
    with pytest.raises(ERechnungFehler, match="nicht wohlgeformt"):
        lesen("kaputt.xml", b"<rsm:CrossIndustryInvoice>")
    ohne_nummer = datei("xrechnung_cii.xml").replace(b"<ram:ID>RE-2026-0412</ram:ID>", b"<ram:ID></ram:ID>")
    with pytest.raises(ERechnungFehler, match="BT-1"):
        lesen("ohne.xml", ohne_nummer)
    falscher_betrag = datei("xrechnung_ubl.xml").replace(b">2142.00<", b">zweitausend<")
    with pytest.raises(ERechnungFehler, match="Ungültiger Betrag"):
        lesen("betrag.xml", falscher_betrag)


def test_faelligkeit_aus_zahlungsbedingungen():
    datum = date(2026, 10, 20)
    assert faelligkeit_aus_text("Zahlbar innerhalb von 14 Tagen ohne Abzug.", datum) == date(2026, 11, 3)
    assert faelligkeit_aus_text("Zahlungsziel: 30 Tage netto", datum) == date(2026, 11, 19)
    # mehrdeutig (Skonto und Netto) oder ohne Zahl: keine geratene Fälligkeit
    assert faelligkeit_aus_text("Innerhalb 8 Tagen 2 % Skonto, zahlbar innerhalb von 30 Tagen netto", datum) is None
    assert faelligkeit_aus_text("Bitte überweisen Sie bald.", datum) is None
    ohne_bt9 = datei("xrechnung_cii.xml").replace(
        b'<ram:DueDateDateTime><udt:DateTimeString format="102">20261103</udt:DateTimeString></ram:DueDateDateTime>',
        b"",
    )
    r = lesen("ohne_bt9.xml", ohne_bt9)
    assert r.faellig_am == date(2026, 11, 3) and r.faelligkeit_aus == "BT-20"
