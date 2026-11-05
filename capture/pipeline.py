"""Verarbeitungsschritte einer Erfassung: aufbereiten (Transkription, Textaufbereitung) → Text prüfen (E3)
→ extrahieren → Regeln → Prüfansicht → Freigabe → Entwurf in Lexware."""

from __future__ import annotations

import logging

from django.utils import timezone

from audit.services import protokolliere

from .dateien import lesen, loeschen
from .models import Datei, Erfassung
from .transkription import transkribieren

log = logging.getLogger(__name__)

KEINE_SPRACHE = "Keine Sprache erkannt. Bitte erneut aufnehmen oder den Text selbst eingeben."


def _abschnitt(titel: str, text: str) -> str:
    return f"### {titel}\n{text.strip()}\n"


def aufbereiten(erfassung: Erfassung) -> None:
    """Transkribiert Audio (und löscht es danach sofort, E8) und bereitet alle Textquellen auf."""
    from .aufbereitung import aufbereiten_datei

    transkripte: list[str] = []
    quellen: list[str] = []
    for datei in Datei.objects.filter(erfassung=erfassung, geloescht_am__isnull=True).order_by("pk"):
        if datei.art == Datei.Art.AUDIO:
            text = transkribieren(lesen(datei), datei.name, datei.mime)
            loeschen(datei)  # Audio nach der Transkription sofort löschen (E8)
            protokolliere(erfassung.firma, "erfassung.audio_geloescht", objekt=datei, daten={"sha256": datei.sha256})
            if text:
                transkripte.append(text)
        elif datei.art != Datei.Art.BILD:  # Bilder gehen direkt als Bild an das Modell
            quellen.append(aufbereiten_datei(datei))
    erfassung.transkript = "\n\n".join(transkripte)
    erfassung.quelltext = "\n".join(q for q in quellen if q)
    hatte_audio = Datei.objects.filter(erfassung=erfassung, art=Datei.Art.AUDIO).exists()
    if hatte_audio and not transkripte:
        erfassung.hinweise = [KEINE_SPRACHE]
    erfassung.status = Erfassung.Status.TRANSKRIBIERT
    erfassung.fehler = ""
    erfassung.save(update_fields=["transkript", "quelltext", "hinweise", "status", "fehler"])


def fehlgeschlagen(erfassung: Erfassung, meldung: str) -> None:
    Erfassung.objects.filter(pk=erfassung.pk).update(status=Erfassung.Status.FEHLER, fehler=meldung[:2000])
    log.warning("Erfassung fehlgeschlagen", extra={"erfassung_id": erfassung.pk, "zeit": timezone.now().isoformat()})
