"""M1-09: Cockpit-Startseite (C1), Postenliste mit Filtern (C2), Kundenansicht (C3), Prognose (C4), mobil (C5)."""

import re
import time
from datetime import date, timedelta
from decimal import Decimal

import pytest
import time_machine
from django.urls import reverse

from ledger.models import Beleg, Kontakt

HEUTE = date(2026, 11, 5)
D = Decimal


@pytest.fixture
def daten(firma, andere_firma):
    bau = Kontakt.objects.create(firma=firma, extern_id="k1", name="Bau AG", kundentyp="unternehmer")
    erika = Kontakt.objects.create(firma=firma, extern_id="k2", name="Erika Musterfrau")

    def beleg(nr, kontakt, offen, faellig, **extra):
        return Beleg.objects.create(
            firma=firma,
            extern_id=nr,
            nummer=nr,
            kontakt=kontakt,
            kontakt_name=kontakt.name if kontakt else "Sammelkunde",
            brutto=extra.pop("brutto", offen),
            offen=offen,
            faellig_am=faellig,
            belegdatum=faellig - timedelta(days=14) if faellig else HEUTE,
            status=extra.pop("status", "offen"),
            **extra,
        )

    beleg("RE1", bau, D("1000.00"), HEUTE - timedelta(days=40), mahnstufe=2)
    beleg("RE2", bau, D("500.00"), HEUTE + timedelta(days=5))
    beleg("RE3", erika, D("74.80"), HEUTE - timedelta(days=5), brutto=D("99.80"))
    beleg("RE4", None, D("200.00"), HEUTE - timedelta(days=95))
    beleg(
        "RE5",
        bau,
        D("0.00"),
        HEUTE - timedelta(days=60),
        status="bezahlt",
        bezahlt_am=HEUTE - timedelta(days=50),
        brutto=D("300.00"),
    )
    beleg("AN1", bau, D("999.00"), HEUTE - timedelta(days=60), art="angebot")
    # fremde Firma: darf nirgends auftauchen
    fremd = Kontakt.objects.create(firma=andere_firma, extern_id="f1", name="Fremd GmbH")
    Beleg.objects.create(
        firma=andere_firma,
        extern_id="F1",
        nummer="F1",
        kontakt=fremd,
        kontakt_name="Fremd GmbH",
        offen=D("777.00"),
        brutto=D("777.00"),
        faellig_am=HEUTE - timedelta(days=10),
    )
    return {"bau": bau, "erika": erika}


@pytest.fixture
def heute():
    with time_machine.travel(date(2026, 11, 5), tick=False):
        yield HEUTE


def _kennzahl(html, name):
    return re.search(rf'data-kennzahl="{name}">([^<]+)<', html).group(1)


@pytest.mark.django_db
def test_startseite_kennzahlen_stimmen_mit_testdaten(client_inhaber, daten, heute):
    html = client_inhaber.get(reverse("web:start")).content.decode()
    assert _kennzahl(html, "summe_offen") == "1.774,80 €"
    assert _kennzahl(html, "summe_ueberfaellig") == "1.274,80 €"
    assert _kennzahl(html, "anzahl_ueberfaellig") == "3"
    assert "Fremd GmbH" not in html
    assert "777,00" not in html
    assert "1–30 Tage überfällig" in html
    assert "Kundentyp" in html  # Erika ohne Kundentyp


@pytest.mark.django_db
def test_startseite_ohne_verbindung_zeigt_hinweis(client_inhaber, firma):
    html = client_inhaber.get(reverse("web:start")).content.decode()
    assert "Noch keine Verbindung zu Lexware" in html
    assert reverse("connectors:lexware") in html


@pytest.mark.django_db
def test_postenliste_filter_kombinierbar(client_inhaber, daten, heute):
    url = reverse("ledger:posten")
    alle = client_inhaber.get(url).content.decode()
    for nr in ("RE1", "RE2", "RE3", "RE4"):
        assert nr in alle
    assert "AN1" not in alle and "RE5" not in alle and "F1" not in alle
    html = client_inhaber.get(url, {"kunde": "bau", "faelligkeit": "ueberfaellig"}).content.decode()
    assert "RE1" in html and "RE2" not in html and "RE3" not in html
    html = client_inhaber.get(url, {"betrag_min": "100", "betrag_max": "600"}).content.decode()
    assert "RE2" in html and "RE4" in html and "RE1" not in html and "RE3" not in html
    html = client_inhaber.get(url, {"mahnstufe": "2"}).content.decode()
    assert "RE1" in html and "RE2" not in html
    html = client_inhaber.get(url, {"faellig_von": "2026-10-25", "faellig_bis": "2026-11-30"}).content.decode()
    assert "RE2" in html and "RE3" in html and "RE1" not in html
    html = client_inhaber.get(url, {"sortierung": "-betrag"}).content.decode()
    assert html.index("RE1") < html.index("RE2") < html.index("RE4") < html.index("RE3")


@pytest.mark.django_db
def test_postenliste_htmx_liefert_nur_liste(client_inhaber, daten, heute):
    antwort = client_inhaber.get(reverse("ledger:posten"), {"kunde": "Erika"}, HTTP_HX_REQUEST="true")
    html = antwort.content.decode()
    assert "<html" not in html
    assert "RE3" in html and "Teilzahlung" in html


@pytest.mark.django_db
def test_postenliste_unter_einer_sekunde_bei_1000_posten(client_inhaber, firma):
    kontakt = Kontakt.objects.create(firma=firma, extern_id="viel", name="Viel GmbH")
    Beleg.objects.bulk_create(
        [
            Beleg(
                firma=firma,
                extern_id=f"x{i}",
                nummer=f"X{i}",
                kontakt=kontakt,
                kontakt_name="Viel GmbH",
                offen=D("10.00") + i,
                brutto=D("10.00") + i,
                faellig_am=HEUTE - timedelta(days=i % 120),
            )
            for i in range(1000)
        ]
    )
    start = time.perf_counter()
    antwort = client_inhaber.get(
        reverse("ledger:posten"), {"kunde": "viel", "faelligkeit": "ueberfaellig", "sortierung": "-betrag"}
    )
    dauer = time.perf_counter() - start
    assert antwort.status_code == 200
    assert dauer < 1.0, f"{dauer:.2f} s"
    start = time.perf_counter()
    client_inhaber.get(reverse("web:start"))
    assert time.perf_counter() - start < 1.0


@pytest.mark.django_db
def test_kundenansicht(client_inhaber, daten, heute):
    bau = daten["bau"]
    html = client_inhaber.get(reverse("ledger:kunde", args=[bau.pk])).content.decode()
    assert "Bau AG" in html
    assert "RE1" in html and "RE2" in html and "RE5" in html
    # RE5: Belegdatum = Fälligkeit - 14, bezahlt 10 Tage nach Fälligkeit → 24 Tage Zahlungsdauer
    assert re.search(r'data-kennzahl="zahlungsdauer">24,0 Tage', html)
    assert "10 Tage nach Fälligkeit" in html


@pytest.mark.django_db
def test_kundenliste_und_navigation(client_inhaber, daten):
    html = client_inhaber.get(reverse("ledger:kunden")).content.decode()
    assert "Bau AG" in html and "Erika Musterfrau" in html and "Fremd GmbH" not in html
    assert 'aria-current="page">Kunden<' in html


@pytest.mark.django_db
def test_mitarbeiter_sieht_cockpit(client_mitarbeiter, daten, heute):
    assert client_mitarbeiter.get(reverse("web:start")).status_code == 200
    assert client_mitarbeiter.get(reverse("ledger:posten")).status_code == 200
