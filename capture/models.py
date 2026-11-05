"""Erfassung per Sprache, Foto, Datei oder Mail (E1–E9). Aus einer Erfassung entsteht höchstens ein Entwurf
im Bestandstool, und das nur nach Freigabe."""

import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.mandant import FirmaModel

ROHDATEI_TAGE = 7
ERFASSUNG_MONATE = 12


def _in_12_monaten() -> datetime:
    return timezone.now() + timedelta(days=365)


def _in_7_tagen() -> datetime:
    return timezone.now() + timedelta(days=ROHDATEI_TAGE)


class Erfassung(FirmaModel):
    class Kanal(models.TextChoices):
        AUFNAHME = "aufnahme", "Sprachaufnahme"
        UPLOAD = "upload", "Upload"
        MAIL = "mail", "Belegpostfach"

    class Status(models.TextChoices):
        WARTET = "wartet", "wird aufbereitet"
        TRANSKRIBIERT = "transkribiert", "Text prüfen"
        EXTRAHIERT = "extrahiert", "wird ausgewertet"
        PRUEFUNG = "pruefung", "Entwurf prüfen"
        FREIGEGEBEN = "freigegeben", "wird übertragen"
        UEBERTRAGEN = "uebertragen", "in Lexware angelegt"
        VERWORFEN = "verworfen", "verworfen"
        FEHLER = "fehler", "Fehler"

    erstellt_von = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    erstellt = models.DateTimeField(default=timezone.now)
    kanal = models.CharField(max_length=20, choices=Kanal.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.WARTET)
    notiz = models.TextField("Notiz", blank=True)
    absender = models.EmailField(blank=True)
    transkript = models.TextField(blank=True)
    transkript_bearbeitet = models.BooleanField(default=False)
    quelltext = models.TextField(blank=True, help_text="Aufbereitete Quellen für die KI (ohne Bilder)")
    ki_ergebnis = models.JSONField(default=dict, blank=True)
    entwurf = models.JSONField(default=dict, blank=True)
    blocker = models.JSONField(default=list, blank=True)
    hinweise = models.JSONField(default=list, blank=True)
    freigegeben_von = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    freigegeben_am = models.DateTimeField(null=True, blank=True)
    ziel_art = models.CharField(max_length=20, blank=True)
    ziel_extern_id = models.CharField(max_length=100, blank=True)
    ziel_url = models.URLField(blank=True)
    fehler = models.TextField(blank=True)
    loeschen_ab = models.DateTimeField(default=_in_12_monaten)

    class Meta:
        verbose_name_plural = "Erfassungen"
        indexes = [models.Index(fields=["firma", "-erstellt"], name="erfassung_firma_idx")]

    def __str__(self) -> str:
        return f"Erfassung {self.pk} ({self.get_status_display()})"


class Datei(FirmaModel):
    class Art(models.TextChoices):
        AUDIO = "audio", "Audio"
        BILD = "bild", "Foto"
        PDF = "pdf", "PDF"
        CSV = "csv", "Zeiterfassung (CSV)"
        TEXT = "text", "Text"
        MAIL = "mail", "E-Mail"

    erfassung = models.ForeignKey(Erfassung, on_delete=models.CASCADE, related_name="dateien")
    name = models.CharField(max_length=255)
    art = models.CharField(max_length=10, choices=Art.choices)
    mime = models.CharField(max_length=100)
    groesse = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    pfad = models.CharField(max_length=255, help_text="Relativ zur Dateiablage (außerhalb des Webroots)")
    erstellt = models.DateTimeField(default=timezone.now)
    loeschen_ab = models.DateTimeField(default=_in_7_tagen)
    geloescht_am = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "Dateien"

    def __str__(self) -> str:
        return self.name


def neuer_pfad(firma_id: int) -> str:
    return f"{firma_id}/{uuid.uuid4().hex}"
