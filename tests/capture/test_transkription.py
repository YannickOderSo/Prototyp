"""M3-02: Transkription mit Mistral (EU), Audio wird danach gelöscht (E8); EU-Endpunkte sind erzwungen (ADR-005)."""

from pathlib import Path

import httpx
import pytest
from django.core.checks import run_checks
from django.test import override_settings
from django.urls import reverse

from audit.models import Protokolleintrag
from capture.models import Datei, Erfassung
from capture.services import anlegen
from tests.conftest import alle_jobs_ausfuehren

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "capture"
pytestmark = pytest.mark.django_db


@pytest.fixture
def memo(firma, inhaber):
    return anlegen(firma, inhaber, "aufnahme", [("aufnahme.webm", (FIX / "memo.webm").read_bytes())])


def test_transkript_und_audio_geloescht(memo, mistral, worker, settings):
    mistral.respond(
        200,
        json={
            "model": "voxtral-mini-latest",
            "text": " Rechnung für Bau AG, zwölf Stunden Malerarbeiten. ",
            "language": "de",
        },
    )
    alle_jobs_ausfuehren(worker)
    memo.refresh_from_db()
    assert memo.status == "transkribiert"
    assert memo.transkript == "Rechnung für Bau AG, zwölf Stunden Malerarbeiten."
    audio = Datei.objects.get(erfassung=memo)
    assert audio.geloescht_am is not None
    assert not (Path(settings.DATEIABLAGE) / audio.pfad).exists()
    assert Protokolleintrag.objects.filter(ereignis="erfassung.audio_geloescht").exists()
    anfrage = mistral.calls.last.request
    assert str(anfrage.url) == "https://api.mistral.ai/v1/audio/transcriptions"
    assert anfrage.headers["Authorization"] == "Bearer test-mistral"
    body = anfrage.content
    assert b'name="model"\r\n\r\nvoxtral-mini-latest' in body
    assert b'name="language"\r\n\r\nde' in body


def test_keine_sprache_erkannt(memo, mistral, worker, client_inhaber):
    mistral.respond(200, json={"text": ""})
    alle_jobs_ausfuehren(worker)
    memo.refresh_from_db()
    assert memo.status == "transkribiert"
    assert "Keine Sprache erkannt" in memo.hinweise[0]
    assert "Keine Sprache erkannt" in client_inhaber.get(reverse("capture:detail", args=[memo.pk])).content.decode()


def test_dienst_nicht_erreichbar_drei_versuche_dann_fehler(memo, mistral, worker, client_inhaber):
    from datetime import timedelta

    import time_machine

    mistral.side_effect = httpx.ConnectError("weg")
    with time_machine.travel(timedelta(0), tick=False) as reise:
        for _ in range(3):
            worker.einen_ausfuehren()
            reise.shift(timedelta(hours=1))
    memo.refresh_from_db()
    assert memo.status == "fehler"
    assert "nicht erreichbar" in memo.fehler
    assert Datei.objects.get(erfassung=memo).geloescht_am is None  # Audio bleibt für den Neuversuch
    # Neuversuch
    mistral.side_effect = None
    mistral.respond(200, json={"text": "Hallo"})
    client_inhaber.post(reverse("capture:neuversuch", args=[memo.pk]))
    alle_jobs_ausfuehren(worker)
    memo.refresh_from_db()
    assert memo.status == "transkribiert" and memo.transkript == "Hallo"


def test_abgelehnt_sofort_fehler(memo, mistral, worker):
    mistral.respond(401)
    worker.einen_ausfuehren()
    memo.refresh_from_db()
    assert memo.status == "fehler"
    assert "abgelehnt" in memo.fehler


def test_ohne_schluessel(memo, worker, settings):
    settings.MISTRAL_API_KEY = ""
    worker.einen_ausfuehren()
    memo.refresh_from_db()
    assert memo.status == "fehler"
    assert "kein Mistral-Schlüssel" in memo.fehler


def test_notiz_und_textdatei_ohne_audio(firma, inhaber, worker):
    erfassung = anlegen(
        firma, inhaber, "upload", [("notiz.txt", "Angebot für Erika Musterfrau".encode())], notiz="eilig"
    )
    alle_jobs_ausfuehren(worker)
    erfassung.refresh_from_db()
    assert erfassung.status == Erfassung.Status.TRANSKRIBIERT
    assert "Angebot für Erika Musterfrau" in erfassung.quelltext
    assert erfassung.transkript == ""


# ------------------------------------------------------------------ EU-Endpunkte (ADR-005)
def _fehler_ids():
    return {f.id for f in run_checks() if f.id and f.id.startswith("cockpit.")}


def test_standard_ist_eu():
    assert _fehler_ids() == set()


@pytest.mark.parametrize(
    ("einstellung", "fehler"),
    [
        ({"BEDROCK_REGION": "us-east-1"}, "cockpit.E001"),
        ({"BEDROCK_MODELL": "global.anthropic.claude-sonnet-5-5"}, "cockpit.E002"),
        ({"BEDROCK_MODELL": "us.anthropic.claude-sonnet-5-5"}, "cockpit.E002"),
        ({"BEDROCK_MODELL": "anthropic.claude-sonnet-5-5"}, "cockpit.E002"),
        ({"MISTRAL_BASIS_URL": "https://api.us.example.com"}, "cockpit.E003"),
        ({"TELEFON_MODELL": "us.anthropic.claude-haiku-5-5"}, "cockpit.E005"),
        ({"TELEFON_MODELL": "global.anthropic.claude-haiku-5-5"}, "cockpit.E005"),
    ],
)
def test_nicht_eu_endpunkte_werden_blockiert(einstellung, fehler):
    with override_settings(**einstellung):
        assert fehler in _fehler_ids()
