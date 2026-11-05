"""M2-01: Mahnplan je Firma mit Standardwerten (D1), Basiszins-Startwerte als Data-Migration."""

from datetime import date, time
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from audit.models import Protokolleintrag
from dunning.models import Basiszins, Mahnplan
from dunning.services import mahnplan_fuer
from dunning.texte import GEGENSTANDSLOS, STANDARD, ersetzen, unbekannte_platzhalter


@pytest.mark.django_db
def test_standardwerte(firma):
    plan = mahnplan_fuer(firma)
    assert (plan.tage_erinnerung, plan.tage_mahnung1, plan.tage_mahnung2) == (7, 21, 35)
    assert plan.erinnerung_aktiv and plan.zinsen_aktiv and plan.pauschale_aktiv
    assert plan.wochentag_freigabe == 0
    assert plan.uhrzeit_freigabe == time(7, 0)
    assert not plan.verzugshinweis_auf_rechnungen
    assert plan.frist_fuer_stufe(1) == 10 and plan.frist_fuer_stufe(2) == 7 and plan.frist_fuer_stufe(0) is None
    assert mahnplan_fuer(firma).pk == plan.pk  # genau einer je Firma


@pytest.mark.django_db
def test_basiszins_startwerte_aus_migration():
    werte = [(b.gueltig_ab, b.satz) for b in Basiszins.objects.order_by("gueltig_ab")]
    assert werte == [
        (date(2025, 1, 1), Decimal("2.2700")),
        (date(2025, 7, 1), Decimal("1.2700")),
        (date(2026, 1, 1), Decimal("1.2700")),
        (date(2026, 7, 1), Decimal("1.5200")),
    ]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("felder", "fehlerfeld"),
    [
        ({"tage_erinnerung": 7, "tage_mahnung1": 13}, "tage_mahnung1"),
        ({"tage_mahnung1": 21, "tage_mahnung2": 27}, "tage_mahnung2"),
        ({"abstand_tage": 6}, "abstand_tage"),
        ({"tage_erinnerung": 0}, "tage_erinnerung"),
    ],
)
def test_mindestabstand_sieben_tage_ist_harte_untergrenze(firma, felder, fehlerfeld):
    plan = Mahnplan(firma=firma, **felder)
    with pytest.raises(ValidationError) as fehler:
        plan.clean()
    assert fehlerfeld in fehler.value.message_dict


@pytest.mark.django_db
def test_ohne_erinnerung_gilt_abstand_nur_zwischen_mahnungen(firma):
    Mahnplan(firma=firma, erinnerung_aktiv=False, tage_erinnerung=7, tage_mahnung1=8, tage_mahnung2=15).clean()


@pytest.mark.django_db
def test_mahnplan_aendern_wird_protokolliert(client_inhaber, firma):
    daten = {
        "automatik_aktiv": "on",
        "erinnerung_aktiv": "on",
        "tage_erinnerung": 10,
        "tage_mahnung1": 24,
        "tage_mahnung2": 40,
        "abstand_tage": 10,
        "frist_mahnung1_tage": 10,
        "frist_mahnung2_tage": 7,
        "zinsen_aktiv": "on",
        "wochentag_freigabe": 2,
        "uhrzeit_freigabe": "06:30",
        "betreff_0": "",
        "text_0": "",
        "betreff_1": "",
        "text_1": "",
        "betreff_2": "",
        "text_2": "",
    }
    antwort = client_inhaber.post(reverse("dunning:mahnplan"), daten)
    assert antwort.status_code == 302
    plan = Mahnplan.objects.get(firma=firma)
    assert plan.tage_erinnerung == 10
    assert not plan.pauschale_aktiv
    eintrag = Protokolleintrag.objects.get(firma=firma, ereignis="mahnplan.geaendert")
    assert eintrag.daten["werte"]["tage_erinnerung"] == "10"
    assert "pauschale_aktiv" in eintrag.daten["werte"]


@pytest.mark.django_db
def test_mahnplan_unzulaessige_werte_und_platzhalter(client_inhaber, firma):
    daten = {
        "tage_erinnerung": 7,
        "tage_mahnung1": 10,
        "tage_mahnung2": 35,
        "abstand_tage": 10,
        "frist_mahnung1_tage": 10,
        "frist_mahnung2_tage": 7,
        "wochentag_freigabe": 0,
        "uhrzeit_freigabe": "07:00",
        "erinnerung_aktiv": "on",
        "text_1": "Hallo {kunde.__class__} {unbekannt}",
    }
    antwort = client_inhaber.post(reverse("dunning:mahnplan"), daten)
    html = antwort.content.decode()
    assert antwort.status_code == 200
    assert "mindestens 7 Tage" in html
    assert "Unbekannte Platzhalter" in html


@pytest.mark.django_db
def test_mahnplan_nur_inhaber(client_freigeber):
    assert client_freigeber.get(reverse("dunning:mahnplan")).status_code == 403


@pytest.mark.django_db
def test_mahnplan_seite_zeigt_basiszins(client_inhaber):
    assert "1,5200 %" in client_inhaber.get(reverse("dunning:mahnplan")).content.decode()


def test_standardtexte_erfuellen_textvorgaben():
    assert "Sicher ist das nur ein Versehen".lower() in STANDARD[0][1].lower()
    for stufe, (betreff, text) in STANDARD.items():
        assert GEGENSTANDSLOS in text
        for verboten in ("schufa", "inkasso", "rechtsanwalt", "anwalt"):
            assert verboten not in text.lower()
        for pflicht in ("{rechnungsnummer}", "{rechnungsdatum}", "{faellig_am}", "{offen}", "{bankverbindung}"):
            assert pflicht in text, (stufe, pflicht)
        if stufe > 0:
            assert "{neue_frist}" in text
            assert "{zinsen_zeile}" in text and "{pauschale_zeile}" in text
        assert not unbekannte_platzhalter(betreff + text)
    assert "gerichtlichen Mahnverfahren" in STANDARD[2][1]
    assert "gerichtlich" not in STANDARD[1][1]


def test_ersetzen_ist_sicher():
    assert ersetzen("{kunde} {kunde.__class__} {fremd}", {"kunde": "Bau AG"}) == "Bau AG {kunde.__class__} {fremd}"
    assert ersetzen("{offen}", {}) == ""
