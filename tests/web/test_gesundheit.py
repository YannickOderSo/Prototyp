"""M4-05: Health-Endpoint (F4) und Fehlererfassung ohne personenbezogene Daten."""

from datetime import timedelta

import pytest
from django.core.checks import run_checks
from django.db import DatabaseError
from django.utils import timezone

from cockpit.fehlererfassung import erlaubter_host, vor_dem_senden
from connectors.models import Verbindung
from jobs.models import Job, WorkerLebenszeichen

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def basiszins_aktuell(db):
    """Unabhängig vom Datum des Testlaufs: Satz für das laufende Halbjahr vorhanden."""
    from decimal import Decimal

    from dunning.models import Basiszins

    heute = timezone.localdate()
    Basiszins.objects.get_or_create(
        gueltig_ab=heute.replace(month=1 if heute.month < 7 else 7, day=1), defaults={"satz": Decimal("1.5")}
    )


def _abfragen(client):
    antwort = client.get("/healthz")
    return antwort.status_code, antwort.json()


def test_alles_gut(client):
    WorkerLebenszeichen.objects.create(name="w1", zuletzt=timezone.now())
    status, daten = _abfragen(client)
    assert status == 200
    assert daten == {
        "status": "ok",
        "pruefungen": {"datenbank": "ok", "worker": "ok", "warteschlange": "ok", "abgleich": "ok", "basiszins": "ok"},
    }


def test_ohne_anmeldung_und_ohne_https_umleitung(client, settings):
    settings.SECURE_SSL_REDIRECT = True
    WorkerLebenszeichen.objects.create(name="w1", zuletzt=timezone.now())
    assert client.get("/healthz").status_code == 200


def test_worker_ausfall_binnen_5_minuten_sichtbar(client):
    WorkerLebenszeichen.objects.create(name="w1", zuletzt=timezone.now() - timedelta(minutes=4, seconds=50))
    assert _abfragen(client)[0] == 200
    WorkerLebenszeichen.objects.filter(name="w1").update(zuletzt=timezone.now() - timedelta(minutes=5, seconds=10))
    status, daten = _abfragen(client)
    assert status == 503
    assert daten["status"] == "fehler" and daten["pruefungen"]["worker"] == "fehler"


def test_ohne_worker_fehler(client):
    assert _abfragen(client)[0] == 503


def test_laufender_job_mit_gueltiger_sperre_zaehlt_als_lebendig(client):
    WorkerLebenszeichen.objects.create(name="w1", zuletzt=timezone.now() - timedelta(minutes=6))
    job = Job.objects.create(typ="x", status="laeuft", gesperrt_bis=timezone.now() + timedelta(seconds=30))
    assert _abfragen(client)[0] == 200
    Job.objects.filter(pk=job.pk).update(gesperrt_bis=timezone.now() - timedelta(seconds=1))
    assert _abfragen(client)[0] == 503  # Sperre abgelaufen: Worker gilt als ausgefallen


def test_rueckstand_und_veralteter_abgleich_sind_warnungen(client, firma, verbindung):
    WorkerLebenszeichen.objects.create(name="w1", zuletzt=timezone.now())
    Verbindung.objects.filter(pk=verbindung.pk).update(letzter_abgleich=timezone.now() - timedelta(hours=27))
    Job.objects.create(typ="x", naechster_versuch=timezone.now() - timedelta(minutes=20))
    status, daten = _abfragen(client)
    assert status == 200
    assert daten["status"] == "warnung"
    assert daten["pruefungen"]["abgleich"] == "warnung" and daten["pruefungen"]["warteschlange"] == "warnung"
    assert "Malerbetrieb" not in str(daten) and str(verbindung.pk) not in str(daten["pruefungen"])


def test_erstimport_haengt_ist_warnung(client, firma, verbindung):
    WorkerLebenszeichen.objects.create(name="w1", zuletzt=timezone.now())
    assert _abfragen(client)[1]["pruefungen"]["abgleich"] == "ok"
    Verbindung.objects.filter(pk=verbindung.pk).update(erstellt=timezone.now() - timedelta(hours=2))
    assert _abfragen(client)[1]["pruefungen"]["abgleich"] == "warnung"


def test_datenbank_fehler_ist_503(client, monkeypatch):
    from web import gesundheit

    def kaputt():
        raise DatabaseError("weg")

    monkeypatch.setattr(gesundheit, "datenbank", kaputt)
    status, daten = _abfragen(client)
    assert status == 503 and daten["pruefungen"]["datenbank"] == "fehler"


def test_nur_get(client):
    assert client.post("/healthz").status_code == 405


@pytest.mark.parametrize(
    ("dsn", "erlaubt"),
    [
        ("https://k@o1.ingest.de.sentry.io/2", True),
        ("https://k@glitchtip.cockpit.example/1", True),
        ("https://k@o1.ingest.sentry.io/2", False),
        ("https://k@o1.ingest.us.sentry.io/2", False),
        ("https://k@sentry.io/2", False),
        ("kein-dsn", False),
    ],
)
def test_nur_eu_fehlererfassung(dsn, erlaubt):
    assert erlaubter_host(dsn) is erlaubt


def test_systemcheck_e004(settings):
    settings.SENTRY_DSN = "https://k@o1.ingest.us.sentry.io/2"
    assert "cockpit.E004" in {f.id for f in run_checks()}
    settings.SENTRY_DSN = "https://k@o1.ingest.de.sentry.io/2"
    assert "cockpit.E004" not in {f.id for f in run_checks()}


def test_vor_dem_senden_entfernt_personenbezug():
    event = {
        "request": {
            "method": "POST",
            "url": "https://cockpit.example/posten/?kunde=M%C3%BCller",
            "query_string": "kunde=Müller",
            "data": {"notiz": "Herr Müller"},
            "cookies": {"sessionid": "geheim"},
            "headers": {"Cookie": "sessionid=geheim"},
        },
        "user": {"id": 7, "email": "inhaber@muster.example", "ip_address": "1.2.3.4"},
        "breadcrumbs": {
            "values": [
                {"category": "query", "message": "SELECT … WHERE name = 'Müller'"},
                {"category": "log", "message": "Job erledigt", "data": {"x": "y"}},
            ]
        },
    }
    ergebnis = vor_dem_senden(event, {})
    assert ergebnis["request"] == {"method": "POST", "url": "https://cockpit.example/posten/"}
    assert ergebnis["user"] == {"id": 7}
    assert ergebnis["breadcrumbs"]["values"] == [{"category": "log", "message": "Job erledigt"}]
    assert "Müller" not in str(ergebnis) and "geheim" not in str(ergebnis)


def test_endgueltiger_jobfehler_wird_als_error_geloggt(worker, caplog):
    from jobs.registry import job

    @job("test.immer_kaputt")
    def _kaputt(j):
        raise RuntimeError("kaputt")

    Job.objects.create(typ="test.immer_kaputt", max_versuche=1)
    with caplog.at_level("WARNING"):
        worker.einen_ausfuehren()
    eintrag = next(r for r in caplog.records if "endgültig" in r.getMessage())
    assert eintrag.levelname == "ERROR" and eintrag.exc_info


def test_worker_lebt_kommando():
    from django.core.management import call_command

    with pytest.raises(SystemExit) as ende:
        call_command("worker_lebt")
    assert ende.value.code == 1
    WorkerLebenszeichen.objects.create(name="w1", zuletzt=timezone.now())
    call_command("worker_lebt")  # kein Fehler


def test_fehlender_basiszins_ist_warnung(client, time_machine):
    WorkerLebenszeichen.objects.create(name="w1", zuletzt=timezone.now())
    time_machine.move_to("2031-07-02 12:00:00+02:00")
    WorkerLebenszeichen.objects.update(zuletzt=timezone.now())
    status, daten = _abfragen(client)
    assert status == 200 and daten["status"] == "warnung" and daten["pruefungen"]["basiszins"] == "warnung"


def test_basiszins_setzen(capsys):
    from decimal import Decimal

    from django.core.management import CommandError, call_command

    from dunning.models import Basiszins

    with pytest.raises(CommandError, match=r"1\. Januar und 1\. Juli"):
        call_command("basiszins_setzen", "2031-02-01", "1.0", "--quelle", "x")
    with pytest.raises(CommandError, match="unplausibel"):
        call_command("basiszins_setzen", "2031-01-01", "25", "--quelle", "x")
    with pytest.raises(CommandError, match="unplausibel"):
        call_command("basiszins_setzen", "2031-01-01", "1.234", "--quelle", "x")
    call_command("basiszins_setzen", "2031-01-01", "-0.88", "--quelle", "Bundesbank, 30.12.2030")
    eintrag = Basiszins.objects.get(gueltig_ab="2031-01-01")
    assert eintrag.satz == Decimal("-0.88") and "Bundesbank" in eintrag.quelle
    with pytest.raises(CommandError, match="bereits"):
        call_command("basiszins_setzen", "2031-01-01", "1.0", "--quelle", "x")
    call_command("basiszins_setzen", "2031-01-01", "1.0", "--quelle", "Korrektur", "--korrigieren")
    assert Basiszins.objects.get(gueltig_ab="2031-01-01").satz == Decimal("1.0")
