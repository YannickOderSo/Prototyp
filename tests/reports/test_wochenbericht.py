"""M4-01: Wöchentlicher Liquiditätsbericht (F1), versendet montags mit der Sammelfreigabe."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.core import mail
from django.urls import reverse

from dunning import sammelmail
from dunning.models import Mahnvorschlag
from ledger.models import Beleg, Kontakt
from reports.wochenbericht import als_text, bericht

pytestmark = pytest.mark.django_db
BERLIN = ZoneInfo("Europe/Berlin")
MONTAG = date(2026, 11, 9)
D = Decimal


@pytest.fixture
def daten(firma, andere_firma):
    k = Kontakt.objects.create(firma=firma, extern_id="k", name="Bau AG", kundentyp="unternehmer")

    def b(nr, **kw):
        return Beleg.objects.create(firma=firma, extern_id=nr, nummer=nr, kontakt=k, kontakt_name="Bau AG", **kw)

    b("B1", status="bezahlt", offen=D("0"), brutto=D("1000.00"), bezahlt_am=MONTAG - timedelta(days=3))
    b("B2", status="bezahlt", offen=D("0"), brutto=D("500.00"), bezahlt_am=MONTAG - timedelta(days=7))
    b("B3", status="bezahlt", offen=D("0"), brutto=D("999.00"), bezahlt_am=MONTAG - timedelta(days=8))  # zu alt
    b("B4", status="bezahlt", offen=D("0"), brutto=D("77.00"), bezahlt_am=MONTAG)  # heute: nächste Woche
    o1 = b("O1", status="ueberfaellig", offen=D("300.00"), brutto=D("300.00"), faellig_am=MONTAG - timedelta(days=40))
    b("O2", status="offen", offen=D("200.00"), brutto=D("200.00"), faellig_am=MONTAG + timedelta(days=5))
    Mahnvorschlag.objects.create(
        firma=firma,
        beleg=o1,
        stufe=0,
        status="versendet",
        gesamt=D("300.00"),
        versendet_am=datetime(2026, 11, 3, 9, 0, tzinfo=BERLIN),
    )
    Mahnvorschlag.objects.create(
        firma=firma,
        beleg=o1,
        stufe=1,
        status="versendet",
        gesamt=D("340.00"),
        versendet_am=datetime(2026, 10, 20, 9, 0, tzinfo=BERLIN),
    )  # zu alt
    Beleg.objects.create(
        firma=andere_firma, extern_id="F", status="bezahlt", brutto=D("5000"), bezahlt_am=MONTAG - timedelta(days=1)
    )
    return firma


def test_bericht_zahlen(daten):
    b = bericht(daten, MONTAG)
    assert (b.von, b.bis) == (date(2026, 11, 2), date(2026, 11, 8))
    assert b.eingegangen_summe == D("1500.00") and b.eingegangen_anzahl == 2
    assert b.kennzahlen.summe_offen == D("500.00")
    assert b.kennzahlen.summe_ueberfaellig == D("300.00")
    assert b.gemahnt[0] == ("Zahlungserinnerung", 1, D("300.00"))
    assert b.gemahnt[1][1] == 0
    assert b.prognose.wochen[0].summe == D("200.00")


def test_text(daten):
    text = als_text(bericht(daten, MONTAG))
    assert "Wochenbericht 02.11. bis 08.11.2026" in text
    assert "Eingegangen: 1.500,00 € (2 Rechnungen vollständig bezahlt)" in text
    assert "Überfällig: 300,00 € (1 Posten)" in text
    assert "Zahlungserinnerung: 1 (300,00 €)" in text
    assert "09.11.–15.11.: 200,00 €" in text


def test_bericht_steht_in_der_montagsmail(daten, inhaber):
    sammelmail.senden(daten, datetime(2026, 11, 9, 7, 0, tzinfo=BERLIN))
    assert "Wochenbericht 02.11. bis 08.11.2026" in mail.outbox[0].body
    assert "Eingegangen: 1.500,00 €" in mail.outbox[0].body


def test_berichtsseite(client_freigeber, daten):
    html = client_freigeber.get(reverse("reports:uebersicht")).content.decode()
    assert "Wochenbericht" in html


def test_berichtsseite_nicht_fuer_mitarbeiter(client_mitarbeiter):
    assert client_mitarbeiter.get(reverse("reports:uebersicht")).status_code == 403
