"""M0-04: Job-Queue mit SKIP LOCKED, Retries mit Backoff, Zeitplan, SIGTERM, hängende Jobs."""

import os
import signal
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from django.db import connection, transaction
from django.utils import timezone

from jobs import registry
from jobs.models import Job, WorkerLebenszeichen, ZeitplanLauf
from jobs.queue import enqueue
from jobs.worker import JobAbbruch, Worker, backoff

AUFRUFE: list[int] = []


@registry.job("test.ok")
def _ok(job):
    AUFRUFE.append(job.pk)


@registry.job("test.fehler")
def _fehler(job):
    raise RuntimeError("geht nicht")


@registry.job("test.abbruch")
def _abbruch(job):
    raise JobAbbruch("dauerhaft kaputt")


@registry.job("test.langsam")
def _langsam(job):
    time.sleep(5)


@pytest.fixture(autouse=True)
def _leeren():
    AUFRUFE.clear()
    yield
    AUFRUFE.clear()


@pytest.mark.django_db
def test_enqueue_und_ausfuehren():
    job = enqueue("test.ok", {"a": 1})
    worker = Worker(name="t")
    assert worker.einen_ausfuehren()
    job.refresh_from_db()
    assert job.status == Job.Status.ERLEDIGT
    assert AUFRUFE == [job.pk]
    assert not worker.einen_ausfuehren()


@pytest.mark.django_db
def test_eindeutiger_schluessel_verhindert_doppelte_aktive_jobs():
    a = enqueue("test.ok", eindeutig="sync:1")
    b = enqueue("test.ok", eindeutig="sync:1")
    assert a.pk == b.pk
    assert Job.objects.count() == 1
    Worker(name="t").einen_ausfuehren()
    c = enqueue("test.ok", eindeutig="sync:1")  # nach Abschluss wieder erlaubt
    assert c.pk != a.pk


@pytest.mark.django_db
def test_verzoegerte_jobs_warten():
    enqueue("test.ok", verzoegerung=timedelta(minutes=5))
    assert not Worker(name="t").einen_ausfuehren()


@pytest.mark.django_db
def test_fehler_wird_mit_backoff_wiederholt_und_endet_als_fehler():
    worker = Worker(name="t")
    with time_machine.travel(datetime(2026, 11, 5, 12, 0, tzinfo=UTC), tick=False) as reise:
        job = enqueue("test.fehler", max_versuche=3)
        assert worker.einen_ausfuehren()
        job.refresh_from_db()
        assert job.status == Job.Status.WARTET
        assert job.versuche == 1
        assert "geht nicht" in job.fehler
        assert timedelta(seconds=30) <= job.naechster_versuch - timezone.now() <= timedelta(seconds=33)
        assert not worker.einen_ausfuehren()  # noch nicht fällig
        reise.shift(timedelta(seconds=40))
        assert worker.einen_ausfuehren()
        job.refresh_from_db()
        assert job.versuche == 2
        assert job.naechster_versuch - timezone.now() >= timedelta(seconds=60)
        reise.shift(timedelta(minutes=5))
        worker.einen_ausfuehren()
        job.refresh_from_db()
        assert job.status == Job.Status.FEHLER
        assert job.versuche == 3


def test_backoff_waechst_und_ist_begrenzt():
    assert backoff(1, lambda: 0) == timedelta(seconds=30)
    assert backoff(2, lambda: 0) == timedelta(seconds=60)
    assert backoff(3, lambda: 0) == timedelta(seconds=120)
    assert backoff(30, lambda: 0) == timedelta(hours=1)
    assert backoff(1, lambda: 1) == timedelta(seconds=33)


@pytest.mark.django_db
def test_abbruch_wird_nicht_wiederholt():
    job = enqueue("test.abbruch")
    Worker(name="t").einen_ausfuehren()
    job.refresh_from_db()
    assert job.status == Job.Status.FEHLER
    assert job.versuche == 1


@pytest.mark.django_db
def test_unbekannter_typ_endet_als_fehler():
    job = enqueue("gibt.es.nicht")
    Worker(name="t").einen_ausfuehren()
    job.refresh_from_db()
    assert job.status == Job.Status.FEHLER


@pytest.mark.django_db
def test_haengender_job_wird_nach_ablauf_der_sperre_freigegeben():
    with time_machine.travel(datetime(2026, 11, 5, 12, 0, tzinfo=UTC), tick=False) as reise:
        job = enqueue("test.ok")
        abgestuerzt = Worker(name="alt", sperrzeit=60)
        assert abgestuerzt.abholen().pk == job.pk  # holt ab und "stürzt ab"
        assert Worker(name="neu").abholen() is None  # gesperrt
        reise.shift(timedelta(seconds=61))
        neu = Worker(name="neu")
        assert neu.einen_ausfuehren()
    job.refresh_from_db()
    assert job.status == Job.Status.ERLEDIGT
    assert job.versuche == 1
    assert job.gesperrt_von == "neu"


@pytest.mark.django_db
def test_haengender_job_ohne_restversuche_endet_als_fehler():
    with time_machine.travel(datetime(2026, 11, 5, 12, 0, tzinfo=UTC), tick=False) as reise:
        job = enqueue("test.ok", max_versuche=1)
        Worker(name="alt", sperrzeit=10).abholen()
        reise.shift(timedelta(seconds=11))
        assert Worker(name="neu").abholen() is None
    job.refresh_from_db()
    assert job.status == Job.Status.FEHLER


@pytest.mark.django_db
def test_zeitlimit_bricht_langsamen_job_ab():
    job = enqueue("test.langsam", max_versuche=1)
    Worker(name="t", sperrzeit=1).einen_ausfuehren()
    job.refresh_from_db()
    assert job.status == Job.Status.FEHLER
    assert "JobZeitueberschreitung" in job.fehler


@pytest.mark.django_db(transaction=True)
def test_skip_locked_zwei_worker_holen_verschiedene_jobs():
    a = enqueue("test.ok")
    b = enqueue("test.ok")
    gesperrt = threading.Event()
    freigeben = threading.Event()
    ergebnis = {}

    def anderer_worker():
        from django.db import connection as conn

        with transaction.atomic():
            job = Job.objects.select_for_update(skip_locked=True).order_by("id").first()
            ergebnis["gesperrt"] = job.pk
            gesperrt.set()
            freigeben.wait(5)
        conn.close()

    t = threading.Thread(target=anderer_worker)
    t.start()
    gesperrt.wait(5)
    try:
        geholt = Worker(name="zwei").abholen()
        assert geholt is not None
        assert {ergebnis["gesperrt"], geholt.pk} == {a.pk, b.pk}
    finally:
        freigeben.set()
        t.join()
    connection.close()


@pytest.mark.django_db
def test_zeitplan_einmal_je_termin():
    registry.zeitplan("test-taeglich", "0 5 * * *", "test.ok")
    try:
        worker = Worker(name="t")
        # 05:03 Berliner Zeit = 04:03 UTC im November
        jetzt = datetime(2026, 11, 5, 4, 3, tzinfo=UTC)
        neu = worker.zeitplan_pruefen(jetzt)
        assert [j.typ for j in neu if j.typ == "test.ok"] == ["test.ok"]
        assert worker.zeitplan_pruefen(jetzt) == []
        assert Worker(name="anderer").zeitplan_pruefen(jetzt + timedelta(minutes=1)) == []
        # nächster Tag
        neu = worker.zeitplan_pruefen(jetzt + timedelta(days=1))
        assert len([j for j in neu if j.typ == "test.ok"]) == 1
        assert ZeitplanLauf.objects.filter(name="test-taeglich").count() == 2
    finally:
        registry._ZEITPLAN.pop("test-taeglich")


@pytest.mark.django_db
def test_zeitplan_holt_nach_neustart_nur_den_letzten_verpassten_termin_nach():
    registry.zeitplan("test-viertel", "*/15 * * * *", "test.ok")
    try:
        worker = Worker(name="t")
        start = datetime(2026, 11, 5, 10, 1, tzinfo=UTC)
        worker.zeitplan_pruefen(start)  # Termin 10:00 UTC = 11:00 lokal
        neu = worker.zeitplan_pruefen(start + timedelta(hours=2))
        assert len([j for j in neu if j.typ == "test.ok"]) == 1
    finally:
        registry._ZEITPLAN.pop("test-viertel")


@pytest.mark.django_db
def test_lebenszeichen_und_schleife_bis_leer():
    enqueue("test.ok")
    enqueue("test.ok")
    worker = Worker(name="leben")
    worker.schleife(bis_leer=True)
    assert len(AUFRUFE) == 2
    assert WorkerLebenszeichen.objects.filter(name="leben").exists()


@pytest.mark.django_db
def test_sigterm_beendet_nach_laufendem_job():
    worker = Worker(name="sig", pause=0.01)
    worker.signale_einrichten()
    try:

        @registry.job("test.sigterm")
        def _sende_sigterm(job):
            os.kill(os.getpid(), signal.SIGTERM)
            AUFRUFE.append(job.pk)

        erster = enqueue("test.sigterm")
        enqueue("test.ok")
        worker.schleife()
        assert worker.stopp
        assert AUFRUFE == [erster.pk]  # laufender Job wurde beendet, kein weiterer gestartet
        assert Job.objects.get(pk=erster.pk).status == Job.Status.ERLEDIGT
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.default_int_handler)
        registry._HANDLER.pop("test.sigterm", None)
