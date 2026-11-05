"""KI-Telefonassistent (ADR-010): Einstellungen je Firma, Gespräche und Rückruf-Notizen."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.mandant import FirmaModel


class Telefonassistent(FirmaModel):
    aktiv = models.BooleanField("Telefonassistent einschalten", default=False)
    begruessung = models.CharField(
        "Begrüßung",
        max_length=300,
        blank=True,
        help_text="Leer lassen für „Guten Tag, Sie sind verbunden mit <Firmenname>.“ Der Pflichthinweis folgt immer.",
    )
    rufnummer = models.CharField(
        "Rufnummer des Assistenten",
        max_length=30,
        blank=True,
        help_text="Vergibt das Belegfluss-Team (Format +49…). Auf diese Nummer leiten Sie verpasste Anrufe um.",
    )
    benachrichtigen = models.BooleanField("Team per Mail über neue Rückrufe informieren", default=True)
    geaendert = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Telefonassistent"
        verbose_name_plural = "Telefonassistenten"
        constraints = [
            models.UniqueConstraint(fields=["firma"], name="telefonassistent_je_firma"),
            models.UniqueConstraint(
                fields=["rufnummer"], condition=~models.Q(rufnummer=""), name="telefonassistent_rufnummer_eindeutig"
            ),
        ]

    def __str__(self) -> str:
        return f"Telefonassistent {self.firma_id}"


def _in_90_tagen() -> datetime:
    return timezone.now() + timedelta(days=90)


class Gespraech(FirmaModel):
    class Kanal(models.TextChoices):
        TELEFON = "telefon", "Anruf"
        TEST = "test", "Testanruf"

    class Status(models.TextChoices):
        LAEUFT = "laeuft", "läuft"
        BEENDET = "beendet", "beendet"
        ABGEBROCHEN = "abgebrochen", "aufgelegt"
        FEHLER = "fehler", "Fehler"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kanal = models.CharField(max_length=10, choices=Kanal.choices, default=Kanal.TELEFON)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.LAEUFT)
    anrufer_nummer = models.CharField(max_length=40, blank=True)
    angerufene_nummer = models.CharField(max_length=40, blank=True)
    begonnen = models.DateTimeField(default=timezone.now)
    beendet = models.DateTimeField(null=True, blank=True)
    runden = models.PositiveSmallIntegerField(default=0)
    verlauf = models.JSONField(default=list, blank=True, help_text="[{rolle, text}] – Text, nie Audio")
    erfasst = models.JSONField(default=dict, blank=True)
    ausfallbetrieb = models.BooleanField(default=False, help_text="Ohne KI mit festen Fragen geführt")
    ki_eingabe = models.PositiveIntegerField(default=0, help_text="KI-Eingabe-Token dieses Gesprächs")
    ki_ausgabe = models.PositiveIntegerField(default=0, help_text="KI-Ausgabe-Token dieses Gesprächs")
    erstellt_von = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    loeschen_ab = models.DateTimeField(default=_in_90_tagen)

    class Meta:
        verbose_name = "Gespräch"
        verbose_name_plural = "Gespräche"
        indexes = [models.Index(fields=["firma", "-begonnen"], name="gespraech_firma_idx")]

    def __str__(self) -> str:
        return f"{self.get_kanal_display()} {self.begonnen:%d.%m.%Y %H:%M}"


class Rueckruf(FirmaModel):
    class Status(models.TextChoices):
        OFFEN = "offen", "offen"
        ERLEDIGT = "erledigt", "erledigt"

    class Dringlichkeit(models.TextChoices):
        NIEDRIG = "niedrig", "kann warten"
        NORMAL = "normal", "normal"
        DRINGEND = "dringend", "dringend"

    gespraech = models.OneToOneField(
        Gespraech, null=True, blank=True, on_delete=models.SET_NULL, related_name="rueckruf"
    )
    test = models.BooleanField(default=False, help_text="Aus einem Testanruf im Browser")
    name = models.CharField(max_length=150, blank=True)
    anliegen = models.TextField(blank=True)
    rueckrufnummer = models.CharField(max_length=40, blank=True)
    beste_zeit = models.CharField(max_length=150, blank=True)
    dringlichkeit = models.CharField(max_length=10, choices=Dringlichkeit.choices, default=Dringlichkeit.NORMAL)
    kontakt = models.ForeignKey(
        "ledger.Kontakt", null=True, blank=True, on_delete=models.SET_NULL, related_name="rueckrufe"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OFFEN)
    erstellt = models.DateTimeField(default=timezone.now)
    erledigt_von = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    erledigt_am = models.DateTimeField(null=True, blank=True)
    notiz = models.TextField("Interne Notiz", blank=True)

    class Meta:
        verbose_name = "Rückruf"
        verbose_name_plural = "Rückrufe"
        indexes = [models.Index(fields=["firma", "status", "-erstellt"], name="rueckruf_offen_idx")]

    def __str__(self) -> str:
        return f"Rückruf {self.name or self.rueckrufnummer or self.pk}"
