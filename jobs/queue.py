"""Jobs einreihen."""

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Job

if TYPE_CHECKING:
    from accounts.models import Firma


def enqueue(
    typ: str,
    payload: dict[str, Any] | None = None,
    *,
    firma: "Firma | None" = None,
    eindeutig: str | None = None,
    verzoegerung: timedelta | None = None,
    max_versuche: int = 5,
) -> Job:
    """Reiht einen Job ein. Mit `eindeutig` entsteht kein zweiter aktiver Job mit demselben Schlüssel."""
    daten = {
        "typ": typ,
        "payload": payload or {},
        "firma": firma,
        "eindeutig_schluessel": eindeutig,
        "max_versuche": max_versuche,
        "naechster_versuch": timezone.now() + (verzoegerung or timedelta(0)),
    }
    if eindeutig is None:
        return Job.objects.create(**daten)
    try:
        with transaction.atomic():
            return Job.objects.create(**daten)
    except IntegrityError:
        vorhanden = Job.objects.filter(
            eindeutig_schluessel=eindeutig, status__in=[Job.Status.WARTET, Job.Status.LAEUFT]
        ).first()
        if vorhanden is None:  # gerade abgeschlossen: neu versuchen
            return Job.objects.create(**daten)
        return vorhanden
