"""Gemeinsame Hilfen für Jobs, die mit dem Bestandstool sprechen."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

from jobs.models import Job
from jobs.worker import JobAbbruch

from .base import AccountingConnector
from .fehler import ConnectorFehler, NichtAutorisiert
from .models import Verbindung
from .services import connector_fuer

T = TypeVar("T")


def verbindung_aus_job(job: Job) -> Verbindung:
    verbindung = Verbindung.objects.select_related("firma").filter(pk=job.payload.get("verbindung_id")).first()
    if verbindung is None or not verbindung.aktiv or (job.firma_id and verbindung.firma_id != job.firma_id):
        raise JobAbbruch("Keine aktive Verbindung")
    return verbindung


@contextmanager
def fehler_behandeln(verbindung: Verbindung) -> Iterator[None]:
    """Abgelehnter Schlüssel: Verbindung auf Fehler setzen, nicht wiederholen. Andere Fehler: Job wiederholt."""
    try:
        yield
    except NichtAutorisiert as fehler:
        Verbindung.objects.filter(pk=verbindung.pk).update(status=Verbindung.Status.FEHLER, fehler=fehler.meldung)
        raise JobAbbruch(fehler.meldung) from fehler
    except ConnectorFehler as fehler:
        Verbindung.objects.filter(pk=verbindung.pk).update(fehler=fehler.meldung)
        if not fehler.wiederholbar:
            raise JobAbbruch(str(fehler)) from fehler
        raise


def mit_connector(job: Job, arbeit: Callable[[Verbindung, AccountingConnector], T]) -> T:
    verbindung = verbindung_aus_job(job)
    with fehler_behandeln(verbindung):
        return arbeit(verbindung, connector_fuer(verbindung))
