"""Worker der Job-Queue.

- holt fällige Jobs mit `SELECT … FOR UPDATE SKIP LOCKED` (mehrere Worker parallel möglich),
- wiederholt fehlgeschlagene Jobs mit exponentiellem Backoff und Jitter,
- gibt hängende Jobs nach Ablauf der Sperre wieder frei,
- plant Zeitplan-Einträge genau einmal je Termin ein,
- beendet sich bei SIGTERM/SIGINT nach dem laufenden Job,
- schreibt ein Lebenszeichen für den Health-Endpoint.

Jeder Job läuft für sich; ein Fehler in einem Job (oder einer Firma) hält die anderen nicht auf.
"""

from __future__ import annotations

import logging
import os
import random
import signal
import socket
import threading
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta
from types import FrameType
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models import Q
from django.utils import timezone

from .cron import Cron
from .models import Job, WorkerLebenszeichen, ZeitplanLauf
from .queue import enqueue
from .registry import handler_fuer, zeitplan_eintraege

log = logging.getLogger(__name__)

BACKOFF_BASIS_SEKUNDEN = 30
BACKOFF_MAX_SEKUNDEN = 60 * 60


class JobAbbruch(Exception):
    """Dauerhafter Fehler: Job wird nicht wiederholt."""


class JobZeitueberschreitung(Exception):
    pass


def backoff(versuche: int, zufall: Callable[[], float] = random.random) -> timedelta:
    """Wartezeit vor dem nächsten Versuch: 30 s, 60 s, 120 s … höchstens 1 h, plus bis zu 10 % Jitter."""
    basis = min(BACKOFF_BASIS_SEKUNDEN * 2 ** max(versuche - 1, 0), BACKOFF_MAX_SEKUNDEN)
    return timedelta(seconds=basis * (1 + 0.1 * zufall()))


class Worker:
    def __init__(self, name: str | None = None, sperrzeit: int = 300, pause: float = 1.0) -> None:
        self.name = name or f"{socket.gethostname()}-{os.getpid()}"
        self.sperrzeit = sperrzeit
        self.pause = pause
        self.stopp = False
        self._letzter_zeitplan = 0.0
        self._letztes_lebenszeichen = 0.0

    # --- Steuerung -------------------------------------------------------
    def signale_einrichten(self) -> None:
        signal.signal(signal.SIGTERM, self._stoppen)
        signal.signal(signal.SIGINT, self._stoppen)

    def _stoppen(self, signum: int, frame: FrameType | None) -> None:
        log.info("Worker beendet sich nach dem laufenden Job", extra={"signal": signum, "worker": self.name})
        self.stopp = True

    def lebenszeichen(self) -> None:
        WorkerLebenszeichen.objects.update_or_create(name=self.name, defaults={"zuletzt": timezone.now()})

    # --- Abholen und Ausführen ------------------------------------------
    def abholen(self) -> Job | None:
        jetzt = timezone.now()
        with transaction.atomic():
            job = (
                Job.objects.select_for_update(skip_locked=True)
                .filter(
                    Q(status=Job.Status.WARTET, naechster_versuch__lte=jetzt)
                    | Q(status=Job.Status.LAEUFT, gesperrt_bis__lt=jetzt)
                )
                .order_by("naechster_versuch", "id")
                .first()
            )
            if job is None:
                return None
            if job.status == Job.Status.LAEUFT:
                # Hängender Job: der vorige Worker ist abgestürzt oder hat die Sperrzeit überschritten
                job.versuche += 1
                job.fehler = f"Sperre von {job.gesperrt_von} abgelaufen, Job wieder freigegeben"
                log.warning("Hängender Job freigegeben", extra={"job_id": job.pk, "typ": job.typ})
                if job.versuche >= job.max_versuche:
                    job.status = Job.Status.FEHLER
                    job.beendet_am = jetzt
                    job.save()
                    return None
            job.status = Job.Status.LAEUFT
            job.gesperrt_bis = jetzt + timedelta(seconds=self.sperrzeit)
            job.gesperrt_von = self.name
            job.gestartet_am = jetzt
            job.save()
            return job

    def ausfuehren(self, job: Job) -> None:
        handler = handler_fuer(job.typ)
        try:
            if handler is None:
                raise JobAbbruch(f"Unbekannter Job-Typ {job.typ}")
            with _zeitlimit(self.sperrzeit):
                handler(job)
        except JobAbbruch as fehler:
            self._fehlgeschlagen(job, fehler, endgueltig=True)
        except Exception as fehler:
            self._fehlgeschlagen(job, fehler, endgueltig=False)
        else:
            Job.objects.filter(pk=job.pk).update(
                status=Job.Status.ERLEDIGT, beendet_am=timezone.now(), gesperrt_bis=None, fehler=""
            )
            log.info("Job erledigt", extra={"job_id": job.pk, "typ": job.typ, "firma_id": job.firma_id})

    def _fehlgeschlagen(self, job: Job, fehler: Exception, endgueltig: bool) -> None:
        versuche = job.versuche + 1
        text = f"{type(fehler).__name__}: {fehler}\n{traceback.format_exc(limit=5)}"[:4000]
        felder: dict[str, object] = {"versuche": versuche, "fehler": text, "gesperrt_bis": None}
        if endgueltig or versuche >= job.max_versuche:
            felder.update(status=Job.Status.FEHLER, beendet_am=timezone.now())
        else:
            felder.update(status=Job.Status.WARTET, naechster_versuch=timezone.now() + backoff(versuche))
        Job.objects.filter(pk=job.pk).update(**felder)
        daten = {"job_id": job.pk, "typ": job.typ, "firma_id": job.firma_id, "versuch": versuche}
        if felder.get("status") == Job.Status.FEHLER:
            # Stufe ERROR: landet in der Fehlererfassung
            log.error("Job endgültig fehlgeschlagen", exc_info=fehler, extra=daten)
        else:
            log.warning("Job fehlgeschlagen, neuer Versuch folgt", extra=daten)

    def einen_ausfuehren(self) -> bool:
        job = self.abholen()
        if job is None:
            return False
        self.ausfuehren(job)
        return True

    # --- Zeitplan --------------------------------------------------------
    def zeitplan_pruefen(self, jetzt: datetime | None = None) -> list[Job]:
        """Plant fällige Zeitplan-Einträge ein, je Termin genau einmal (auch bei mehreren Workern)."""
        jetzt = jetzt or timezone.now()
        zone = ZoneInfo(settings.TIME_ZONE)
        lokal_jetzt = jetzt.astimezone(zone).replace(tzinfo=None)
        neu: list[Job] = []
        for eintrag in zeitplan_eintraege():
            cron = Cron(eintrag.cron)
            letzter = ZeitplanLauf.objects.filter(name=eintrag.name).order_by("-termin").first()
            # Ohne vorigen Lauf nur kurz zurückschauen, damit ein Neustart keine alten Termine nachholt
            basis = (
                letzter.termin.astimezone(zone).replace(tzinfo=None) if letzter else lokal_jetzt - timedelta(minutes=10)
            )
            termin = None
            kandidat = cron.naechster(basis)
            while kandidat <= lokal_jetzt:
                termin = kandidat
                kandidat = cron.naechster(kandidat)
            if termin is None:
                continue
            termin_aware = termin.replace(tzinfo=zone)
            try:
                with transaction.atomic():
                    ZeitplanLauf.objects.create(name=eintrag.name, termin=termin_aware)
            except IntegrityError:
                continue  # anderer Worker war schneller
            neu.append(
                enqueue(
                    eintrag.typ,
                    {"termin": termin_aware.isoformat()},
                    eindeutig=f"zeitplan:{eintrag.name}:{termin_aware.isoformat()}",
                    max_versuche=eintrag.max_versuche,
                )
            )
        return neu

    # --- Hauptschleife ---------------------------------------------------
    def schleife(self, bis_leer: bool = False) -> None:
        while not self.stopp:
            if not connection.in_atomic_block:
                close_old_connections()
            jetzt = time.monotonic()
            if jetzt - self._letztes_lebenszeichen > 30:
                self.lebenszeichen()
                self._letztes_lebenszeichen = jetzt
            if jetzt - self._letzter_zeitplan > 20:
                self.zeitplan_pruefen()
                self._letzter_zeitplan = jetzt
            gearbeitet = self.einen_ausfuehren()
            if not gearbeitet:
                if bis_leer:
                    return
                time.sleep(self.pause)


class _zeitlimit:
    """Bricht einen Job nach `sekunden` per SIGALRM ab (nur im Hauptthread möglich)."""

    def __init__(self, sekunden: int) -> None:
        self.sekunden = sekunden
        self.aktiv = threading.current_thread() is threading.main_thread() and hasattr(signal, "SIGALRM")

    def _ausloesen(self, signum: int, frame: FrameType | None) -> None:
        raise JobZeitueberschreitung(f"Job dauerte länger als {self.sekunden} s")

    def __enter__(self) -> None:
        if self.aktiv:
            self._vorher = signal.signal(signal.SIGALRM, self._ausloesen)
            signal.setitimer(signal.ITIMER_REAL, self.sekunden)

    def __exit__(self, *args: object) -> None:
        if self.aktiv:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._vorher)
