"""Health-Endpoint (F4): Datenbank, Worker-Lebenszeichen, Warteschlange, letzter Abgleich je Verbindung,
Basiszins für das laufende Halbjahr gepflegt.

Öffentlich erreichbar für den externen Uptime-Check, daher nur Status je Prüfung, keine Zahlen und keine IDs.
Details stehen im Log. HTTP 503, wenn Datenbank oder Worker ausgefallen sind: Ein Worker-Ausfall ist so binnen
5 Minuten sichtbar (Lebenszeichen alle 30 Sekunden; ein laufender Job mit gültiger Sperre zählt als lebendig,
die Sperre läuft nach höchstens 5 Minuten ab).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_not_required
from django.db import DatabaseError, connection
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

log = logging.getLogger(__name__)

WORKER_GRENZE = timedelta(minutes=5)
RUECKSTAND_GRENZE = timedelta(minutes=15)
ABGLEICH_GRENZE = timedelta(hours=26)  # Nachtabgleich täglich 2 Uhr plus Puffer
ERSTIMPORT_GRENZE = timedelta(hours=1)

OK, WARNUNG, FEHLER = "ok", "warnung", "fehler"


def datenbank() -> tuple[str, dict[str, object]]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return OK, {}


def worker(jetzt: datetime) -> tuple[str, dict[str, object]]:
    from jobs.models import Job, WorkerLebenszeichen

    letztes = WorkerLebenszeichen.objects.order_by("-zuletzt").values_list("zuletzt", flat=True).first()
    alter = (jetzt - letztes).total_seconds() if letztes else None
    if letztes and jetzt - letztes <= WORKER_GRENZE:
        return OK, {"lebenszeichen_sek": int(alter or 0)}
    if Job.objects.filter(status=Job.Status.LAEUFT, gesperrt_bis__gt=jetzt).exists():
        return OK, {"lebenszeichen_sek": alter, "laufender_job": True}
    return FEHLER, {"lebenszeichen_sek": alter}


def warteschlange(jetzt: datetime) -> tuple[str, dict[str, object]]:
    from jobs.models import Job

    rueckstand = Job.objects.filter(status=Job.Status.WARTET, naechster_versuch__lt=jetzt - RUECKSTAND_GRENZE).count()
    return (WARNUNG if rueckstand else OK), {"rueckstand": rueckstand}


def abgleich(jetzt: datetime) -> tuple[str, dict[str, object]]:
    from connectors.models import Verbindung

    aktiv = Verbindung.objects.filter(status=Verbindung.Status.AKTIV)
    veraltet = aktiv.filter(letzter_abgleich__lt=jetzt - ABGLEICH_GRENZE).count()
    ohne_import = aktiv.filter(letzter_abgleich__isnull=True, erstellt__lt=jetzt - ERSTIMPORT_GRENZE).count()
    fehler = Verbindung.objects.filter(status=Verbindung.Status.FEHLER).count()
    daten: dict[str, object] = {"aktiv": aktiv.count(), "veraltet": veraltet + ohne_import, "fehler": fehler}
    return (WARNUNG if veraltet or ohne_import or fehler else OK), daten


def basiszins(jetzt: datetime) -> tuple[str, dict[str, object]]:
    """Fehlt der Satz für das laufende Halbjahr, entstehen keine Zinsen: Warnung an den Betrieb."""
    from dunning.models import Basiszins

    heute = timezone.localdate(jetzt)
    halbjahr = heute.replace(month=1 if heute.month < 7 else 7, day=1)
    vorhanden = Basiszins.objects.filter(gueltig_ab=halbjahr).exists()
    return (OK if vorhanden else WARNUNG), {"halbjahr": halbjahr.isoformat()}


@never_cache
@require_GET
@login_not_required
def healthz(request: HttpRequest) -> JsonResponse:
    jetzt = timezone.now()
    ergebnisse: dict[str, tuple[str, dict[str, object]]] = {}
    try:
        ergebnisse["datenbank"] = datenbank()
        ergebnisse["worker"] = worker(jetzt)
        ergebnisse["warteschlange"] = warteschlange(jetzt)
        ergebnisse["abgleich"] = abgleich(jetzt)
        ergebnisse["basiszins"] = basiszins(jetzt)
    except DatabaseError:
        log.exception("Health: Datenbank nicht erreichbar")
        ergebnisse["datenbank"] = (FEHLER, {})
    status = {name: s for name, (s, _) in ergebnisse.items()}
    if FEHLER in status.values():
        gesamt = FEHLER
    elif WARNUNG in status.values():
        gesamt = WARNUNG
    else:
        gesamt = OK
    if gesamt != OK:
        log.warning("Health: %s", gesamt, extra={"pruefungen": {n: d for n, (_, d) in ergebnisse.items()}})
    return JsonResponse({"status": gesamt, "pruefungen": status}, status=503 if gesamt == FEHLER else 200)
