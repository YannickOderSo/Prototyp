"""M3-04: Textaufbereitung: PDF-Text, CSV-Zeiterfassung (deterministisch verdichtet), Mail-Parsing."""

from decimal import Decimal
from pathlib import Path

import pytest

from capture import aufbereitung
from capture.models import Datei
from capture.services import anlegen
from tests.conftest import alle_jobs_ausfuehren

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "capture"


@pytest.mark.parametrize(
    ("wert", "erwartet"),
    [
        ("4,5", Decimal("4.5")),
        ("4.5", Decimal("4.5")),
        ("1:30", Decimal("1.5")),
        ("01:15:00", Decimal("1.25")),
        ("0:45", Decimal("0.75")),
        ("", Decimal("0")),
        ("1.234,5", Decimal("1234.5")),
    ],
)
def test_stunden_lesen(wert, erwartet):
    assert aufbereitung.stunden_lesen(wert) == erwartet


@pytest.mark.parametrize("wert", ["abc", "-2", "1:2:3:4", "1:xx"])
def test_stunden_ungueltig(wert):
    with pytest.raises(ValueError):
        aufbereitung.stunden_lesen(wert)


def test_zeiterfassung_deutsch_semikolon():
    q = aufbereitung.zeiterfassung("zeiten.csv", (FIX / "zeiten.csv").read_bytes())
    assert q.herkunft == "zeiterfassung"
    assert q.stunden == [
        {"kunde": "Bau AG", "projekt": "Neubau Nord", "stunden": "7.75"},
        {"kunde": "Erika Musterfrau", "projekt": "Wohnzimmer", "stunden": "2.00"},
    ]
    assert "Kunde Bau AG, Projekt Neubau Nord: 7.75 Stunden" in q.text
    assert "Erfasste Tage: 2026-11-02 bis 2026-11-03" in q.text
    assert "bereits addiert" in q.text


def test_zeiterfassung_clockify_export():
    q = aufbereitung.zeiterfassung("clockify.csv", (FIX / "clockify.csv").read_bytes())
    assert {"kunde": "Bau AG", "projekt": "Neubau Nord", "stunden": "5.75"} in q.stunden
    assert {"kunde": "(ohne Kunde)", "projekt": "Intern", "stunden": "0.50"} in q.stunden
    assert "2026-11-02 bis 2026-11-03" in q.text


def test_zeiterfassung_mit_fehlerhafter_zeile():
    daten = b"Kunde;Projekt;Stunden\nBau AG;Nord;2\nBau AG;Nord;viel\n"
    q = aufbereitung.zeiterfassung("x.csv", daten)
    assert q.stunden[0]["stunden"] == "2.00"
    assert "1 Zeile(n)" in q.hinweise[0]


def test_zeiterfassung_ohne_zeiten():
    q = aufbereitung.zeiterfassung("leer.csv", b"Kunde;Projekt\nBau AG;Nord\n")
    assert q.text == ""
    assert "keine Zeiten" in q.hinweise[0]


def test_pdf_text():
    q = aufbereitung.pdf("aufmass.pdf", (FIX / "aufmass.pdf").read_bytes())
    assert "Aufmass Wohnzimmer 42 qm" in q.text


def test_kaputtes_pdf():
    q = aufbereitung.pdf("kaputt.pdf", b"%PDF-1.4 kaputt")
    assert q.text == ""
    assert "konnte nicht gelesen werden" in q.hinweise[0] or "keinen lesbaren Text" in q.hinweise[0]


def test_mail_mit_anhang():
    _nachricht, text, anhaenge = aufbereitung.mail_zerlegen((FIX / "auftrag.eml").read_bytes())
    assert "Von: Petra Polier <petra.polier@bau-ag.example>" in text
    assert "Betreff: Stunden Neubau Nord" in text
    assert "Bitte abrechnen" in text
    assert [n for n, _ in anhaenge] == ["zeiten.csv"]
    assert "Anhänge: zeiten.csv" in aufbereitung.mail("auftrag.eml", (FIX / "auftrag.eml").read_bytes()).text


def test_html_mail_ohne_tags():
    daten = (
        b"From: a@b.example\nSubject: X\nContent-Type: text/html; charset=utf-8\n\n<p>Bitte <b>Angebot</b> schicken</p>"
    )
    _, text, _ = aufbereitung.mail_zerlegen(daten)
    assert "Bitte Angebot schicken" in text
    assert "<b>" not in text


def test_lange_texte_werden_gekappt():
    q = aufbereitung.notiz("lang.txt", ("x" * 20000).encode())
    assert len(q.text) == aufbereitung.MAX_ZEICHEN_JE_QUELLE
    assert q.hinweise


@pytest.mark.django_db
def test_pipeline_bereitet_alles_auf(firma, inhaber, worker):
    erfassung = anlegen(
        firma,
        inhaber,
        "upload",
        [
            ("aufmass.pdf", (FIX / "aufmass.pdf").read_bytes()),
            ("auftrag.eml", (FIX / "auftrag.eml").read_bytes()),
            ("foto.jpg", (FIX / "stundenzettel.jpg").read_bytes()),
        ],
    )
    alle_jobs_ausfuehren(worker)
    erfassung.refresh_from_db()
    assert erfassung.status == "transkribiert"
    arten = [q["art"] for q in erfassung.quellen]
    assert arten == ["pdf", "mail", "zeiterfassung"]  # Anhang der Mail wurde eigene Datei
    assert erfassung.quellen[2]["stunden"][0]["stunden"] == "7.75"
    assert sorted(Datei.objects.filter(erfassung=erfassung).values_list("art", flat=True)) == [
        "bild",
        "csv",
        "mail",
        "pdf",
    ]
    assert "Aufmass Wohnzimmer" in erfassung.quelltext
