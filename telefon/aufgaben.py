"""Jobs des Telefonassistenten."""

from django.conf import settings
from django.core.mail import EmailMessage
from django.urls import reverse

from accounts.models import Mitgliedschaft
from audit.services import protokolliere
from jobs.models import Job
from jobs.registry import job
from jobs.worker import JobAbbruch

from .models import Rueckruf


@job("telefon.benachrichtigen")
def _benachrichtigen(j: Job) -> None:
    """Mail an das Team: nur Name, Dringlichkeit und Link (ADR-010). Das Anliegen steht nur in der App."""
    rueckruf = (
        Rueckruf.objects.select_related("firma").filter(pk=j.payload.get("rueckruf_id"), firma_id=j.firma_id).first()
    )
    if rueckruf is None:
        raise JobAbbruch("Rückruf nicht gefunden")
    adressen = sorted(
        Mitgliedschaft.objects.filter(firma=rueckruf.firma, nutzer__is_active=True).values_list(
            "nutzer__email", flat=True
        )
    )
    if not adressen:
        return
    dringend = rueckruf.dringlichkeit == Rueckruf.Dringlichkeit.DRINGEND
    wer = rueckruf.name or rueckruf.rueckrufnummer or "Anrufer"
    link = settings.BASIS_URL + reverse("telefon:rueckruf", args=[rueckruf.pk])
    text = (
        f"Guten Tag,\n\nder Telefonassistent hat für {rueckruf.firma.name} einen Anruf angenommen.\n\n"
        f"Name: {rueckruf.name or '–'}\nDringlichkeit: {rueckruf.get_dringlichkeit_display()}\n\n"
        f"Anliegen und Rückrufnummer finden Sie in Belegfluss (Anmeldung nötig):\n{link}\n"
    )
    EmailMessage(f"{'Dringender ' if dringend else ''}Rückruf: {wer}", text, to=adressen).send(fail_silently=False)
    protokolliere(rueckruf.firma, "telefon.benachrichtigt", objekt=rueckruf, daten={"empfaenger": len(adressen)})
