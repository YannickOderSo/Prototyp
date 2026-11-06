"""M9-04 (K5): PDF ohne E-Rechnung. Die KI liest vor, ein Mensch bestätigt; ohne Bestätigung kein Posten."""

from decimal import Decimal

import pytest
from django.urls import reverse

from audit.models import Protokolleintrag
from capture.models import KiVerbrauch
from jobs.models import Job
from ledger.models import Beleg, Kontakt
from quellen import kopien
from quellen.ki import steht_im_text
from tests.conftest import alle_jobs_ausfuehren
from tests.ki_fake import antwort
from tests.quellen.hilfen import text_pdf

pytestmark = pytest.mark.django_db

PDF = text_pdf(
    "Malerbetrieb Muster GmbH - Malerweg 5 - 10117 Berlin",
    "Bau AG, Bahnhofstr. 1, 10115 Berlin",
    "Rechnung Nr. 2026-117    Datum: 01.10.2026",
    "Malerarbeiten Treppenhaus",
    "Gesamtbetrag brutto: 1.190,00 EUR",
    "Zahlbar innerhalb von 14 Tagen ohne Abzug.",
)


def ki_werte(**ueberschreiben):
    werte = {
        "art": "rechnung",
        "nummer": "2026-117",
        "belegdatum": "2026-10-01",
        "faellig_am": "",
        "zahlungsziel_tage": 14,
        "waehrung": "EUR",
        "verkaeufer": "Malerbetrieb Muster GmbH",
        "kaeufer_name": "Bau AG",
        "kaeufer_email": "",
        "kaeufer_anschrift": "Bau AG\nBahnhofstr. 1\n10115 Berlin",
        "brutto": "1190.00",
        "zahlbetrag": "1190.00",
        "bezug": "",
        "unsicher": [],
    }
    werte.update(ueberschreiben)
    return werte


def _einlesen_und_lesen(firma, worker, ki, *antworten):
    client = ki(*antworten)
    kopie = kopien.einlesen(firma, "rechnung-117.pdf", PDF)
    assert kopie.status == "pruefung" and kopie.daten["ki"] == "wartet"
    assert Job.objects.filter(typ="quellen.ki_lesen", firma=firma).count() == 1
    alle_jobs_ausfuehren(worker)
    kopie.refresh_from_db()
    return kopie, client


def test_ki_liest_vor_aber_legt_keinen_posten_an(firma, worker, ki):
    kopie, client = _einlesen_und_lesen(firma, worker, ki, antwort(ki_werte()))
    assert kopie.ki_gelesen and kopie.status == "pruefung" and kopie.daten["ki"] == "fertig"
    assert kopie.daten["nummer"] == "2026-117" and kopie.daten["zahlbetrag"] == "1190.00"
    # Fälligkeit rechnet die Regel, nicht die KI
    assert kopie.daten["faellig_am"] == "2026-10-15" and kopie.daten["faelligkeit_aus"] == "Zahlungsziel 14 Tage"
    assert "Rechnungsdatum plus 14 Tage" in kopie.grund and "steht so nicht im PDF" not in kopie.grund
    assert not Beleg.objects.exists() and not Kontakt.objects.exists()
    assert KiVerbrauch.objects.get(firma=firma).vorgaenge == 1
    assert Protokolleintrag.objects.filter(ereignis="rechnungskopie.ki_gelesen").exists()
    # Datenminimierung: nur der PDF-Text als Daten von Dritten, keine Stammdaten
    aufruf = client.messages.aufrufe[0]
    inhalt = aufruf["messages"][0]["content"]
    assert inhalt.startswith('<quelle name="rechnung-117.pdf">') and "Gesamtbetrag brutto" in inhalt
    assert "stammdaten" not in inhalt and aufruf["output_config"]["format"]["type"] == "json_schema"


def test_mensch_bestaetigt_dann_entsteht_der_posten(firma, worker, ki, client_inhaber, inhaber):
    kopie, _ = _einlesen_und_lesen(firma, worker, ki, antwort(ki_werte()))
    seite = client_inhaber.get(reverse("quellen:kopie", args=[kopie.pk])).content.decode()
    assert "Die Werte unten hat die KI aus dem PDF gelesen" in seite and 'value="2026-117"' in seite
    assert 'value="1.190,00"' in seite  # deutsch formatiert; beim Absenden wieder richtig gelesen (unten)
    client_inhaber.post(
        reverse("quellen:kopie", args=[kopie.pk]),
        {
            "aktion": "uebernehmen",
            "art": "rechnung",
            "nummer": "2026-117",
            "belegdatum": "2026-10-01",
            "faellig_am": "2026-10-15",
            "kaeufer_name": "Bau AG",
            "kaeufer_anschrift": "Bau AG\nBahnhofstr. 1\n10115 Berlin",
            "brutto": "1.190,00",
            "zahlbetrag": "1.190,00",
        },
    )
    kopie.refresh_from_db()
    assert kopie.status == "angelegt" and kopie.geprueft_von == inhaber and kopie.text == ""
    assert kopie.beleg.offen == Decimal("1190.00") and kopie.beleg.quelle == "kopie"
    eintrag = Protokolleintrag.objects.get(ereignis="rechnungskopie.posten_angelegt")
    assert eintrag.nutzer == inhaber and eintrag.daten["bestaetigt"] is True


def test_gegenprobe_markiert_erfundene_werte(firma, worker, ki):
    kopie, _ = _einlesen_und_lesen(
        firma,
        worker,
        ki,
        antwort(ki_werte(nummer="2026-171", zahlbetrag="1109.00", unsicher=["Der Stempel überdeckt das Datum."])),
    )
    assert "Rechnungsnummer „2026-171“ steht so nicht im PDF" in kopie.grund
    assert "offener Betrag „1109.00“ steht so nicht im PDF" in kopie.grund
    assert "Der Stempel überdeckt das Datum." in kopie.grund
    assert "Rechnungsbetrag" not in kopie.grund  # 1.190,00 steht im PDF


def test_fremder_verkaeufer_und_unklare_art(firma, worker, ki):
    kopie, _ = _einlesen_und_lesen(
        firma, worker, ki, antwort(ki_werte(verkaeufer="Baustoffe Schmidt KG", art="unklar"))
    )
    assert "nicht Ihre Firma" in kopie.grund and "vorbelegt ist „Rechnung“" in kopie.grund
    assert kopie.daten["art"] == "rechnung"


def test_ki_fehler_laesst_eintragen_von_hand_zu(firma, worker, ki):
    kopie, _ = _einlesen_und_lesen(firma, worker, ki, antwort(stop_reason="refusal", text=""))
    assert not kopie.ki_gelesen and kopie.status == "pruefung" and kopie.daten["ki"] == "fehler"
    assert "Die KI konnte das PDF nicht lesen" in kopie.grund
    assert Job.objects.get(typ="quellen.ki_lesen").status == "fehler"


def test_kostenlimit(firma, worker, ki, settings):
    settings.KI_LIMIT_VORGAENGE_MONAT = 1
    from capture.extraktion import verbrauch_buchen

    verbrauch_buchen(firma, 10, 10)
    kopie, client = _einlesen_und_lesen(firma, worker, ki, antwort(ki_werte()))
    assert client.messages.aufrufe == [] and "Monatslimit" in kopie.grund


def test_von_hand_erledigt_bevor_die_ki_fertig_ist(firma, worker, ki, inhaber):
    ki(antwort(ki_werte()))
    kopie = kopien.einlesen(firma, "rechnung-117.pdf", PDF)
    kopien.verwerfen(kopie, inhaber)
    alle_jobs_ausfuehren(worker)
    kopie.refresh_from_db()
    assert kopie.status == "verworfen" and not kopie.ki_gelesen
    assert not KiVerbrauch.objects.exists()


def test_steht_im_text():
    text = "Summe 2.142,00 €  Datum 3. November 2026, fällig 20.10.2026 Nr.  RE-1"
    assert steht_im_text(text, Decimal("2142.00")) and not steht_im_text(text, Decimal("2142.50"))
    from datetime import date

    assert steht_im_text(text, date(2026, 11, 3)) and steht_im_text(text, date(2026, 10, 20))
    assert steht_im_text(text, "RE-1") and not steht_im_text(text, "RE-2")
    assert steht_im_text("Total 2,142.00 EUR", Decimal("2142.00"))
