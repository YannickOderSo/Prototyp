"""Jobs der Rechnungskopien."""

from jobs.models import Job
from jobs.registry import job
from jobs.worker import JobAbbruch

from .models import Rechnungskopie


@job("quellen.ki_lesen")
def _ki_lesen(j: Job) -> None:
    """K5: PDF ohne E-Rechnung von der KI vorlesen lassen. Legt nie einen Posten an."""
    from capture.extraktion import ExtraktionFehler

    from . import ki

    kopie = (
        Rechnungskopie.objects.select_related("firma").filter(pk=j.payload.get("kopie_id"), firma_id=j.firma_id).first()
    )
    if kopie is None:
        raise JobAbbruch("Rechnungskopie nicht gefunden")
    if kopie.status != Rechnungskopie.Status.PRUEFUNG or kopie.ki_gelesen or not kopie.text:
        return
    try:
        ki.lesen(kopie)
    except ExtraktionFehler as fehler:
        if not fehler.wiederholbar or j.versuche + 1 >= j.max_versuche:
            ki.fehlgeschlagen(kopie, str(fehler))
            raise JobAbbruch(str(fehler)) from fehler
        raise
