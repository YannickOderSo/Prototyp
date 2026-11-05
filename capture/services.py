"""Erfassungen anlegen und Verarbeitung anstoßen."""

from __future__ import annotations

from collections.abc import Iterable

from django.db import transaction

from accounts.models import Firma, Nutzer
from audit.services import protokolliere
from jobs.models import Job
from jobs.queue import enqueue

from .dateien import DateiAbgelehnt, speichern
from .models import Datei, Erfassung


def aufbereitung_einplanen(erfassung: Erfassung) -> Job:
    return enqueue(
        "capture.aufbereiten",
        {"erfassung_id": erfassung.pk},
        firma=erfassung.firma,
        eindeutig=f"aufbereiten:{erfassung.pk}",
        max_versuche=3,  # KI-Pipeline: nach 3 Versuchen Fehler anzeigen
    )


def anlegen(
    firma: Firma,
    nutzer: Nutzer | None,
    kanal: str,
    dateien: Iterable[tuple[str, bytes]],
    notiz: str = "",
    absender: str = "",
) -> Erfassung:
    """Legt eine Erfassung mit Dateien an. Wirft DateiAbgelehnt; dann wird nichts gespeichert."""
    dateien = list(dateien)
    if not dateien and not notiz.strip():
        raise DateiAbgelehnt("Bitte nehmen Sie etwas auf, laden Sie eine Datei hoch oder schreiben Sie eine Notiz.")
    with transaction.atomic():
        erfassung = Erfassung.objects.create(
            firma=firma, erstellt_von=nutzer, kanal=kanal, notiz=notiz.strip()[:20000], absender=absender
        )
        gespeichert: list[Datei] = []
        try:
            for name, daten in dateien:
                gespeichert.append(speichern(erfassung, name, daten))
        except DateiAbgelehnt:
            from .dateien import loeschen

            for datei in gespeichert:
                loeschen(datei)
            raise
        protokolliere(
            firma,
            "erfassung.angelegt",
            nutzer=nutzer,
            objekt=erfassung,
            daten={"kanal": kanal, "dateien": [d.art for d in gespeichert]},
        )
        aufbereitung_einplanen(erfassung)
    return erfassung
