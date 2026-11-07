"""M3-07: Prüfansicht mit Herkunft, Hinweisen, Blockern und Bearbeiten (E6)."""

from decimal import Decimal

import pytest
from django.urls import reverse

from audit.models import Protokolleintrag
from capture.entwurf import regeln_anwenden
from capture.models import Erfassung
from ledger.models import Artikel, Kontakt
from tests.ki_fake import ergebnis

pytestmark = pytest.mark.django_db


@pytest.fixture
def erfassung(firma, mitarbeiter, verbindung):  # Lexware-Weg: Artikel und Kunden aus dem Spiegel
    Kontakt.objects.create(firma=firma, extern_id="k1", name="Bau AG", kundennummer="10001")
    Kontakt.objects.create(firma=firma, extern_id="k2", name="Erika Musterfrau")
    Artikel.objects.create(
        firma=firma,
        extern_id="art-maler-stunde",
        bezeichnung="Malerarbeiten Facharbeiter",
        einheit="Stunde",
        netto=Decimal("58.00"),
        steuersatz=Decimal("19"),
        typ="SERVICE",
    )
    Artikel.objects.create(
        firma=firma,
        extern_id="art-farbe",
        bezeichnung="Dispersionsfarbe",
        einheit="Eimer",
        netto=Decimal("49.90"),
        steuersatz=Decimal("19"),
        typ="PRODUCT",
    )
    ki = ergebnis(
        positionen=[
            {
                "artikel_id": "art-maler-stunde",
                "beschreibung": "Malerarbeiten",
                "menge": 12,
                "einheit": "Stunde",
                "quelle": "Sprachmemo",
                "herkunft": "gesprochen",
            },
            {
                "artikel_id": "",
                "beschreibung": "Sondermaß-Rahmen",
                "menge": 2,
                "einheit": "Stück",
                "quelle": "Foto 1",
                "herkunft": "foto",
            },
        ],
        offene_fragen=["Soll die Anfahrt berechnet werden?"],
    )
    e = Erfassung.objects.create(
        firma=firma, erstellt_von=mitarbeiter, kanal="aufnahme", status="pruefung", ki_ergebnis=ki, transkript="…"
    )
    regeln_anwenden(e)
    return e


def test_ansicht_zeigt_herkunft_blocker_hinweise(client_inhaber, erfassung):
    html = client_inhaber.get(reverse("capture:detail", args=[erfassung.pk])).content.decode()
    assert "Rechnungsentwurf prüfen" in html
    assert ">gehört<" in html and ">aus Foto<" in html
    assert "aus Stammdaten (Lexware-Artikel „Malerarbeiten Facharbeiter“)" in html
    assert "Noch nicht freigabefähig" in html and "Sondermaß-Rahmen" in html
    assert "Soll die Anfahrt berechnet werden?" in html
    assert 'data-summe="netto">696,00 €' in html
    assert "disabled" in html.split("Freigeben und als Entwurf")[0].rsplit("<button", 1)[1]


def test_nutzer_setzt_preis_und_entwurf_wird_freigabefaehig(client_mitarbeiter, erfassung, mitarbeiter):
    antwort = client_mitarbeiter.post(
        reverse("capture:pruefen", args=[erfassung.pk]),
        {
            "belegart": "rechnung",
            "kunde": "k1",
            "leistung_von": "2026-11-02",
            "leistung_bis": "2026-11-04",
            "angebot_nummer": "",
            "pos-0-beschreibung": "Malerarbeiten Wohnzimmer",
            "pos-0-menge": "12,5",
            "pos-0-einheit": "Stunde",
            "pos-0-artikel_id": "art-maler-stunde",
            "pos-1-beschreibung": "Sondermaß-Rahmen",
            "pos-1-menge": "2",
            "pos-1-einheit": "Stück",
            "pos-1-artikel_id": "",
            "pos-1-preis_nutzer": "85,50",
            "pos-1-steuersatz_nutzer": "19",
        },
    )
    assert antwort.status_code == 302
    erfassung.refresh_from_db()
    assert erfassung.blocker == []
    p0, p1 = erfassung.entwurf["positionen"]
    assert (p0["menge"], p0["summe"]) == ("12.5", "725.00")
    assert (p1["netto"], p1["preis_herkunft"], p1["herkunft"]) == ("85.50", "vom Nutzer gesetzt", "foto")
    assert erfassung.entwurf["summen"]["netto"] == "896.00"
    assert erfassung.ki_ergebnis["positionen"][0]["menge"] == 12  # KI-Ergebnis bleibt unverändert
    assert Protokolleintrag.objects.get(ereignis="erfassung.entwurf_bearbeitet").nutzer == mitarbeiter


def test_kunde_wechseln_entfernen_und_hinzufuegen(client_inhaber, erfassung):
    client_inhaber.post(
        reverse("capture:pruefen", args=[erfassung.pk]),
        {
            "belegart": "angebot",
            "kunde": "k2",
            "leistung_von": "",
            "leistung_bis": "",
            "pos-0-beschreibung": "Malerarbeiten",
            "pos-0-menge": "12",
            "pos-0-einheit": "Stunde",
            "pos-0-artikel_id": "art-maler-stunde",
            "pos-1-entfernen": "1",
            "neu-beschreibung": "Farbe",
            "neu-menge": "3",
            "neu-einheit": "Eimer",
            "neu-artikel_id": "art-farbe",
        },
    )
    erfassung.refresh_from_db()
    assert erfassung.entwurf["belegart"] == "angebot"
    assert erfassung.entwurf["kunde_extern_id"] == "k2"
    assert [p["beschreibung"] for p in erfassung.entwurf["positionen"]] == ["Malerarbeiten", "Farbe"]
    assert erfassung.entwurf["positionen"][1]["herkunft"] == "nutzer"
    assert erfassung.blocker == []  # Angebot braucht keinen Leistungszeitraum
    html = client_inhaber.get(reverse("capture:detail", args=[erfassung.pk])).content.decode()
    assert "vom Nutzer ergänzt" in html


def test_ki_darf_keinen_preis_setzen(client_inhaber, erfassung):
    """Selbst wenn ein Preisfeld im KI-Ergebnis stünde, nutzen die Regeln es nicht ohne Nutzeraktion."""
    erfassung.eingabe = {}
    erfassung.ki_ergebnis["positionen"][1]["preis"] = 0
    erfassung.save()
    entwurf = regeln_anwenden(erfassung)
    assert entwurf.positionen[1].netto is None


def test_nur_in_pruefung_bearbeitbar(client_inhaber, erfassung):
    erfassung.status = "uebertragen"
    erfassung.save()
    antwort = client_inhaber.post(reverse("capture:pruefen", args=[erfassung.pk]), {"belegart": "angebot"}, follow=True)
    assert "nicht mehr bearbeitet" in antwort.content.decode()


def test_verwerfen(client_mitarbeiter, erfassung):
    client_mitarbeiter.post(reverse("capture:verwerfen", args=[erfassung.pk]))
    erfassung.refresh_from_db()
    assert erfassung.status == "verworfen"
    assert Protokolleintrag.objects.filter(ereignis="erfassung.verworfen").exists()


def test_mitarbeiter_sieht_keinen_freigabeknopf(client_mitarbeiter, erfassung):
    html = client_mitarbeiter.get(reverse("capture:detail", args=[erfassung.pk])).content.decode()
    assert "Freigeben dürfen nur Inhaber und Freigeber" in html
