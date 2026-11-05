"""Verarbeitungsschritte einer Erfassung: aufbereiten (Transkription, Textaufbereitung) → Text prüfen (E3)
→ extrahieren → Regeln → Prüfansicht → Freigabe → Entwurf in Lexware."""

from __future__ import annotations

import logging

from audit.services import protokolliere

from . import aufbereitung
from .dateien import DateiAbgelehnt, lesen, loeschen, speichern
from .models import Datei, Erfassung
from .transkription import transkribieren

log = logging.getLogger(__name__)

KEINE_SPRACHE = "Keine Sprache erkannt. Bitte erneut aufnehmen oder den Text selbst eingeben."

AUFBEREITER = {
    Datei.Art.PDF: aufbereitung.pdf,
    Datei.Art.CSV: aufbereitung.zeiterfassung,
    Datei.Art.MAIL: aufbereitung.mail,
    Datei.Art.TEXT: aufbereitung.notiz,
}


def _anhaenge_auspacken(erfassung: Erfassung, hinweise: list[str]) -> None:
    """Anhänge hochgeladener Mails werden eigene Dateien der Erfassung (Typprüfung wie beim Upload)."""
    for datei in Datei.objects.filter(erfassung=erfassung, art=Datei.Art.MAIL, geloescht_am__isnull=True):
        _, _, anhaenge = aufbereitung.mail_zerlegen(lesen(datei))
        for name, daten in anhaenge:
            try:
                speichern(erfassung, name, daten)
            except DateiAbgelehnt as fehler:
                hinweise.append(f"Anhang „{name}“ übersprungen: {fehler}")


def aufbereiten(erfassung: Erfassung) -> None:
    """Transkribiert Audio (und löscht es danach sofort, E8) und bereitet alle Textquellen auf."""
    hinweise: list[str] = []
    if erfassung.kanal != Erfassung.Kanal.MAIL:
        _anhaenge_auspacken(erfassung, hinweise)
    transkripte: list[str] = []
    quellen: list[aufbereitung.Quelle] = []
    hatte_audio = False
    for datei in Datei.objects.filter(erfassung=erfassung, geloescht_am__isnull=True).order_by("pk"):
        if datei.art == Datei.Art.AUDIO:
            hatte_audio = True
            text = transkribieren(lesen(datei), datei.name, datei.mime)
            loeschen(datei)  # Audio nach der Transkription sofort löschen (E8)
            protokolliere(erfassung.firma, "erfassung.audio_geloescht", objekt=datei, daten={"sha256": datei.sha256})
            if text:
                transkripte.append(text)
        elif datei.art in AUFBEREITER:
            quelle = AUFBEREITER[datei.art](datei.name, lesen(datei))
            quellen.append(quelle)
            hinweise.extend(quelle.hinweise)
    if hatte_audio and not transkripte:
        hinweise.insert(0, KEINE_SPRACHE)
    erfassung.transkript = "\n\n".join(transkripte)
    erfassung.quellen = [q.als_dict() for q in quellen if q.text]
    erfassung.quelltext = "\n\n".join(f"### {q.name}\n{q.text}" for q in quellen if q.text)
    erfassung.hinweise = hinweise
    erfassung.status = Erfassung.Status.TRANSKRIBIERT
    erfassung.fehler = ""
    erfassung.save(update_fields=["transkript", "quellen", "quelltext", "hinweise", "status", "fehler"])


def fehlgeschlagen(erfassung: Erfassung, meldung: str) -> None:
    Erfassung.objects.filter(pk=erfassung.pk).update(status=Erfassung.Status.FEHLER, fehler=meldung[:2000])
    log.warning("Erfassung fehlgeschlagen", extra={"erfassung_id": erfassung.pk})
