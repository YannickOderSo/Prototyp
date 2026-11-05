"""Jobs der Erfassung."""

from jobs.models import Job
from jobs.registry import job
from jobs.worker import JobAbbruch

from .models import Erfassung
from .pipeline import aufbereiten, fehlgeschlagen
from .transkription import TranskriptionFehler


def _erfassung(j: Job) -> Erfassung:
    erfassung = (
        Erfassung.objects.select_related("firma").filter(pk=j.payload.get("erfassung_id"), firma_id=j.firma_id).first()
    )
    if erfassung is None:
        raise JobAbbruch("Erfassung nicht gefunden")
    return erfassung


@job("capture.aufbereiten")
def _aufbereiten(j: Job) -> None:
    erfassung = _erfassung(j)
    if erfassung.status != Erfassung.Status.WARTET:
        return
    try:
        aufbereiten(erfassung)
    except TranskriptionFehler as fehler:
        if not fehler.wiederholbar or j.versuche + 1 >= j.max_versuche:
            fehlgeschlagen(erfassung, str(fehler))
            raise JobAbbruch(str(fehler)) from fehler
        raise
