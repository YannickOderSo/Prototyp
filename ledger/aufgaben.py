"""Jobs des Spiegels: Erstimport, Zahlungshistorie, nächtlicher Abgleich, Einzelbeleg."""

from connectors.jobs import mit_connector
from connectors.models import Verbindung
from jobs.models import Job
from jobs.queue import enqueue
from jobs.registry import job, zeitplan

from . import abgleich


def erstimport_einplanen(verbindung: Verbindung) -> Job:
    return enqueue(
        "ledger.erstimport",
        {"verbindung_id": verbindung.pk},
        firma=verbindung.firma,
        eindeutig=f"erstimport:{verbindung.pk}",
    )


@job("ledger.erstimport")
def _erstimport(j: Job) -> None:
    mit_connector(j, abgleich.erstimport)
    enqueue("ledger.zahlungshistorie", j.payload, firma=j.firma, eindeutig=f"historie:{j.payload['verbindung_id']}")


@job("ledger.zahlungshistorie")
def _zahlungshistorie(j: Job) -> None:
    mit_connector(j, abgleich.zahlungshistorie)


@job("ledger.nachtabgleich")
def _nachtabgleich(j: Job) -> None:
    mit_connector(j, abgleich.nachtabgleich)


@job("ledger.beleg_abgleichen")
def _beleg(j: Job) -> None:
    mit_connector(j, lambda v, c: abgleich.beleg_abgleichen(v, c, str(j.payload["extern_id"])))


@job("ledger.nachtabgleich_alle")
def _nachtabgleich_alle(j: Job) -> None:
    """Verteilt den Abgleich auf einen Job je Verbindung (eine Firma blockiert die anderen nicht)."""
    for verbindung in Verbindung.objects.filter(status=Verbindung.Status.AKTIV).exclude(schluessel_verschluesselt=""):
        enqueue(
            "ledger.nachtabgleich",
            {"verbindung_id": verbindung.pk},
            firma=verbindung.firma,
            eindeutig=f"nachtabgleich:{verbindung.pk}",
        )


zeitplan("nachtabgleich", "0 2 * * *", "ledger.nachtabgleich_alle")
