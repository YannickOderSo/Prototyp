"""M9-09 (ADR-011 Stufe 1): Ohne Lexware wird der freigegebene Entwurf als Positionsliste zum Abtippen ausgegeben.

Keine Nummer, kein Beleg, nichts verlässt die App; Preise nur, wenn ein Mensch sie gesetzt hat."""

import pytest
from django.urls import reverse

from audit.models import Protokolleintrag
from capture.entwurf import regeln_anwenden
from capture.models import Erfassung
from ledger.models import Kontakt
from tests.ki_fake import ergebnis

pytestmark = pytest.mark.django_db


def _positionen():
    return [
        {
            "artikel_id": "",
            "beschreibung": "Malerarbeiten Treppenhaus",
            "menge": 12.5,
            "einheit": "Stunde",
            "quelle": "Sprachmemo",
            "herkunft": "gesprochen",
        },
        {
            "artikel_id": "",
            "beschreibung": "=Dispersionsfarbe weiß",  # Formel-Anfang: im CSV entschärft
            "menge": 3,
            "einheit": "Eimer",
            "quelle": "Foto 1",
            "herkunft": "foto",
        },
    ]


@pytest.fixture
def erfassung(firma, mitarbeiter):
    e = Erfassung.objects.create(
        firma=firma,
        erstellt_von=mitarbeiter,
        kanal="aufnahme",
        status="pruefung",
        transkript="Treppenhaus Gasthof Linde, zwölfeinhalb Stunden, drei Eimer Farbe",
        ki_ergebnis=ergebnis(kunde="Gasthof Linde", positionen=_positionen()),
    )
    regeln_anwenden(e)
    return e


def test_ohne_lexware_blockieren_kunde_und_preis_nicht(erfassung):
    assert erfassung.blocker == []
    assert any("Gasthof Linde" in h and "Kundenstamm" in h for h in erfassung.hinweise)
    assert any("2 Position(en) ohne Preis" in h for h in erfassung.hinweise)
    assert erfassung.entwurf["kunde_name"] == "Gasthof Linde"


def test_mit_lexware_bleiben_es_blocker(firma, mitarbeiter, verbindung):
    e = Erfassung.objects.create(
        firma=firma, erstellt_von=mitarbeiter, kanal="aufnahme", status="pruefung",
        ki_ergebnis=ergebnis(kunde="Gasthof Linde", positionen=_positionen()),
    )  # fmt: skip
    regeln_anwenden(e)
    assert any("nicht in Lexware angelegt" in b for b in e.blocker)
    assert any("Kein passender Lexware-Artikel" in b for b in e.blocker)


def test_menge_fehlt_bleibt_blocker(firma, mitarbeiter):
    positionen = _positionen()
    positionen[0]["menge"] = 0
    e = Erfassung.objects.create(
        firma=firma, erstellt_von=mitarbeiter, kanal="aufnahme", status="pruefung",
        ki_ergebnis=ergebnis(kunde="Gasthof Linde", positionen=positionen),
    )  # fmt: skip
    regeln_anwenden(e)
    assert any("Menge fehlt" in b for b in e.blocker)


def test_freigeben_gibt_positionsliste_aus(client_inhaber, inhaber, erfassung, lexware_api):
    # Preis für eine Position setzt der Mensch selbst
    erfassung.eingabe["positionen"][0].update({"preis_nutzer": "58.00", "steuersatz_nutzer": "19"})
    erfassung.save()
    seite = client_inhaber.get(reverse("capture:detail", args=[erfassung.pk])).content.decode()
    assert "Freigeben und als Positionsliste ausgeben" in seite and "Lexware-Artikel" not in seite
    antwort = client_inhaber.post(reverse("capture:freigeben", args=[erfassung.pk]), follow=True)
    erfassung.refresh_from_db()
    assert erfassung.status == "ausgegeben" and erfassung.freigegeben_von == inhaber
    seite = antwort.content.decode()
    assert "Entwurf – keine Rechnung." in seite and "Positionsliste für eine Rechnung" in seite
    assert "Malerarbeiten Treppenhaus" in seite and "12,5" in seite and "58,00 €" in seite and "725,00 €" in seite
    assert "in Ihrem Programm" in seite  # Position ohne Preis
    assert "1 ohne Preis nicht enthalten" in seite
    assert 'style="' not in seite
    assert lexware_api.calls.call_count == 0
    eintrag = Protokolleintrag.objects.get(ereignis="erfassung.positionsliste")
    assert eintrag.nutzer == inhaber and eintrag.daten["ohne_preis"] == 1


def test_csv(client_inhaber, inhaber, erfassung):
    client_inhaber.post(reverse("capture:freigeben", args=[erfassung.pk]))
    antwort = client_inhaber.get(reverse("capture:positionsliste_csv", args=[erfassung.pk]))
    assert antwort["Content-Type"].startswith("text/csv")
    assert "Positionsliste-Entwurf_" in antwort["Content-Disposition"]
    zeilen = antwort.content.decode("utf-8-sig").splitlines()
    assert zeilen[0].startswith("Pos.;Beschreibung;Menge;Einheit")
    assert zeilen[1] == "1;Malerarbeiten Treppenhaus;12,5;Stunde;;;"
    assert zeilen[2].startswith("2;'=Dispersionsfarbe weiß;3;Eimer")  # gegen Formeln in Tabellenprogrammen
    assert Protokolleintrag.objects.filter(ereignis="erfassung.positionsliste_csv", nutzer=inhaber).exists()


def test_mitarbeiter_darf_nicht_freigeben(client_mitarbeiter, erfassung):
    assert client_mitarbeiter.post(reverse("capture:freigeben", args=[erfassung.pk])).status_code == 403
    erfassung.refresh_from_db()
    assert erfassung.status == "pruefung"


def test_vor_der_freigabe_keine_liste(client_inhaber, erfassung):
    assert client_inhaber.get(reverse("capture:positionsliste", args=[erfassung.pk])).status_code == 404
    assert client_inhaber.get(reverse("capture:positionsliste_csv", args=[erfassung.pk])).status_code == 404


def test_kunde_aus_dem_kundenstamm(firma, mitarbeiter):
    Kontakt.objects.create(firma=firma, extern_id="lokal-1", name="Gasthof Linde")
    e = Erfassung.objects.create(
        firma=firma, erstellt_von=mitarbeiter, kanal="aufnahme", status="pruefung",
        ki_ergebnis=ergebnis(kunde="Gasthof Linde", positionen=_positionen()),
    )  # fmt: skip
    regeln_anwenden(e)
    assert e.entwurf["kunde_extern_id"] == "lokal-1"
    assert not any("Kundenstamm" in h for h in e.hinweise)
