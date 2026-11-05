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


BEARBEITBAR = (Erfassung.Status.TRANSKRIBIERT, Erfassung.Status.PRUEFUNG, Erfassung.Status.FEHLER)


def extraktion_einplanen(erfassung: Erfassung) -> Job:
    return enqueue(
        "capture.extrahieren",
        {"erfassung_id": erfassung.pk},
        firma=erfassung.firma,
        eindeutig=f"extrahieren:{erfassung.pk}",
        max_versuche=3,
    )


def transkript_speichern(erfassung: Erfassung, nutzer: Nutzer, text: str, erzeugen: bool) -> None:
    """E3: Text vor der Extraktion prüfen und ändern; auf Wunsch (neu) einen Entwurf erzeugen lassen."""
    if erfassung.status not in BEARBEITBAR:
        raise ValueError("Diese Erfassung kann nicht mehr bearbeitet werden.")
    text = text.strip()[:30000]
    if text != erfassung.transkript:
        erfassung.transkript = text
        erfassung.transkript_bearbeitet = True
        protokolliere(erfassung.firma, "erfassung.transkript_bearbeitet", nutzer=nutzer, objekt=erfassung)
    if erzeugen:
        if (
            not (erfassung.transkript or erfassung.quelltext or erfassung.notiz)
            and not Datei.objects.filter(erfassung=erfassung, art=Datei.Art.BILD, geloescht_am__isnull=True).exists()
        ):
            raise ValueError("Es gibt keinen Text und kein Foto, aus dem ein Entwurf entstehen könnte.")
        erfassung.status = Erfassung.Status.EXTRAHIERT
        erfassung.fehler = ""
        erfassung.save()
        extraktion_einplanen(erfassung)
    else:
        erfassung.save()
