"""Jobs der Mahnautomatik."""

from accounts.models import Firma
from connectors.models import Verbindung
from jobs.models import Job
from jobs.queue import enqueue
from jobs.registry import job, zeitplan
from jobs.worker import JobAbbruch

from . import angebote, sammelmail
from .models import Mahnplan
from .versand import versand_job
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
    angebote.vorschlaege_erzeugen(j.firma)  # ADR-009: Erinnerungen an Angebote kurz vor Ablauf


job("dunning.versenden")(versand_job)
job("dunning.angebot_erinnern")(angebote.versand_job)


@job("dunning.sammelmails_pruefen")
def _sammelmails_pruefen(j: Job) -> None:
    """Alle 15 Minuten: Firmen, deren Sammelfreigabe-Termin erreicht ist, bekommen einen eigenen Job."""
    for firma in Firma.objects.filter(aktiv=True):
        if sammelmail.faellig(firma):
            enqueue("dunning.sammelmail", {}, firma=firma, eindeutig=f"sammelmail:{firma.pk}")


@job("dunning.sammelmail")
def _sammelmail(j: Job) -> None:
    if j.firma is None:
        raise JobAbbruch("Firma fehlt")
    if sammelmail.faellig(j.firma):
        sammelmail.senden(j.firma)


zeitplan("mahnvorschlaege", "0 5 * * *", "dunning.vorschlaege_alle")
zeitplan("sammelmails", "*/15 * * * *", "dunning.sammelmails_pruefen")
