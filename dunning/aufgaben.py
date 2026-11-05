"""Jobs der Mahnautomatik."""

from accounts.models import Firma
from connectors.models import Verbindung
from jobs.models import Job
from jobs.queue import enqueue
from jobs.registry import job, zeitplan
from jobs.worker import JobAbbruch

from .models import Mahnplan
from .vorschlaege import vorschlagslauf


@job("dunning.vorschlaege_alle")
def _alle(j: Job) -> None:
    """Täglich 5 Uhr: ein Job je Firma mit aktiver Verbindung und eingeschalteter Automatik."""
    firmen = (
        Firma.objects.filter(aktiv=True)
        .filter(pk__in=Verbindung.objects.filter(status=Verbindung.Status.AKTIV).values("firma_id"))
        .exclude(pk__in=Mahnplan.objects.filter(automatik_aktiv=False).values("firma_id"))
    )
    datum = str(j.payload.get("termin", ""))[:10]
    for firma in firmen:
        enqueue("dunning.vorschlaege", {}, firma=firma, eindeutig=f"vorschlaege:{firma.pk}:{datum}")


@job("dunning.vorschlaege")
def _vorschlaege(j: Job) -> None:
    if j.firma is None:
        raise JobAbbruch("Firma fehlt")
    vorschlagslauf(j.firma)


zeitplan("mahnvorschlaege", "0 5 * * *", "dunning.vorschlaege_alle")
