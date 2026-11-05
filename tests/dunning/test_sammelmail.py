"""M2-07: Sammelfreigabe-Mail montags 7 Uhr mit Link ins Cockpit (Login nötig, Link gibt nichts frei)."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest
import time_machine
from django.core import mail
from django.urls import reverse

from audit.models import Protokolleintrag
from dunning import sammelmail
from dunning.models import Mahnplan, Mahnvorschlag, Sammelmail
from dunning.vorschlaege import vorschlagslauf
from jobs.queue import enqueue
from tests.conftest import alle_jobs_ausfuehren

pytestmark = pytest.mark.django_db
BERLIN = ZoneInfo("Europe/Berlin")
MONTAG_7 = datetime(2026, 11, 9, 7, 0, tzinfo=BERLIN)


@pytest.fixture
def team(firma, inhaber, freigeber, mitarbeiter):
    return firma


def test_faellig_montag_ab_7_uhr_einmal_je_woche(team):
    assert not sammelmail.faellig(team, datetime(2026, 11, 9, 6, 59, tzinfo=BERLIN))
    assert sammelmail.faellig(team, MONTAG_7)
    assert sammelmail.faellig(team, datetime(2026, 11, 9, 15, 0, tzinfo=BERLIN))
    assert not sammelmail.faellig(team, datetime(2026, 11, 10, 7, 0, tzinfo=BERLIN))  # Dienstag: nicht nachholen
    sammelmail.senden(team, MONTAG_7)
    assert not sammelmail.faellig(team, datetime(2026, 11, 9, 8, 0, tzinfo=BERLIN))
    assert sammelmail.faellig(team, datetime(2026, 11, 16, 7, 0, tzinfo=BERLIN))


def test_eigener_wochentag_und_uhrzeit(team):
    Mahnplan.objects.create(firma=team, wochentag_freigabe=2, uhrzeit_freigabe=time(6, 30))
    assert not sammelmail.faellig(team, MONTAG_7)
    assert sammelmail.faellig(team, datetime(2026, 11, 11, 6, 30, tzinfo=BERLIN))


def test_mail_an_inhaber_und_freigeber_mit_link_ohne_token(team, inhaber, freigeber, mitarbeiter, posten):
    with time_machine.travel(datetime(2026, 11, 9, 5, 0, tzinfo=BERLIN), tick=False):
        posten(tage=10)
        posten(tage=12)
        posten(tage=10, kundentyp="unbekannt")
        vorschlagslauf(team)
    lauf = sammelmail.senden(team, MONTAG_7)
    assert lauf.woche == "2026-W46"
    (nachricht,) = mail.outbox
    assert sorted(nachricht.to) == sorted([inhaber.email, freigeber.email])
    assert mitarbeiter.email not in nachricht.to
    assert nachricht.subject == "Malerbetrieb Muster GmbH: 2 Erinnerungen und Mahnungen zur Freigabe"
    assert "Zahlungserinnerung: 2 (zusammen 2.380,00 €)" in nachricht.body
    assert "fehlt der Kundentyp" in nachricht.body
    link = "http://localhost:8000" + reverse("dunning:freigabe")
    assert link in nachricht.body
    assert "?" not in link and "token" not in nachricht.body.lower()
    assert "gibt dieser Link selbst nichts frei" in nachricht.body
    assert Protokolleintrag.objects.filter(ereignis="sammelmail.versendet").exists()
    assert sammelmail.senden(team, MONTAG_7) is None  # zweites Mal in derselben Woche: nichts
    assert len(mail.outbox) == 1


def test_link_fuehrt_nur_zur_anmeldung(client, team, posten):
    with time_machine.travel(datetime(2026, 11, 9, 5, 0, tzinfo=BERLIN), tick=False):
        posten(tage=10)
        vorschlagslauf(team)
    antwort = client.get(reverse("dunning:freigabe"))
    assert antwort.status_code == 302
    assert antwort["Location"].startswith(reverse("accounts:login"))
    assert Mahnvorschlag.objects.get().status == "vorgeschlagen"


def test_ohne_vorschlaege(team):
    sammelmail.senden(team, MONTAG_7)
    assert "keine Erinnerungen oder Mahnungen" in mail.outbox[0].body


def test_zeitplan_alle_15_minuten_und_job(team, worker):
    from jobs.registry import zeitplan_eintraege

    assert any(e.typ == "dunning.sammelmails_pruefen" and e.cron == "*/15 * * * *" for e in zeitplan_eintraege())
    with time_machine.travel(datetime(2026, 11, 9, 7, 5, tzinfo=BERLIN), tick=False):
        enqueue("dunning.sammelmails_pruefen")
        alle_jobs_ausfuehren(worker)
        enqueue("dunning.sammelmails_pruefen")
        alle_jobs_ausfuehren(worker)
    assert Sammelmail.objects.count() == 1
    assert len(mail.outbox) == 1


def test_firma_ohne_freigeber_bekommt_keine_mail(firma, mitarbeiter):
    assert sammelmail.senden(firma, MONTAG_7) is None
    assert mail.outbox == []
