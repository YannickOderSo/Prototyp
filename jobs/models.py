"""Postgres-basierte Job-Queue (ADR-002): kein Redis, kein Celery."""

from django.db import models
from django.db.models import Q
from django.utils import timezone


class Job(models.Model):
    class Status(models.TextChoices):
        WARTET = "wartet", "wartet"
        LAEUFT = "laeuft", "läuft"
        ERLEDIGT = "erledigt", "erledigt"
        FEHLER = "fehler", "Fehler"

    typ = models.CharField(max_length=100)
    payload = models.JSONField(default=dict, blank=True)
    firma = models.ForeignKey("accounts.Firma", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.WARTET)
    versuche = models.PositiveIntegerField(default=0)
    max_versuche = models.PositiveIntegerField(default=5)
    naechster_versuch = models.DateTimeField(default=timezone.now)
    gesperrt_bis = models.DateTimeField(null=True, blank=True)
    gesperrt_von = models.CharField(max_length=100, blank=True)
    fehler = models.TextField(blank=True)
    eindeutig_schluessel = models.CharField(max_length=200, null=True, blank=True)
    erstellt = models.DateTimeField(default=timezone.now)
    gestartet_am = models.DateTimeField(null=True, blank=True)
    beendet_am = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "naechster_versuch"], name="job_faellig_idx")]
        constraints = [
            # Ein Schlüssel darf nur einmal aktiv (wartend oder laufend) sein
            models.UniqueConstraint(
                fields=["eindeutig_schluessel"],
                condition=Q(status__in=["wartet", "laeuft"]),
                name="job_eindeutig_aktiv",
            )
        ]

    def __str__(self) -> str:
        return f"{self.typ}#{self.pk} ({self.status})"


class ZeitplanLauf(models.Model):
    """Merkt sich je Zeitplan-Eintrag, welcher Termin bereits eingeplant wurde (einmal je Termin)."""

    name = models.CharField(max_length=100)
    termin = models.DateTimeField()
    erstellt = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["name", "termin"], name="zeitplan_einmal_je_termin")]

    def __str__(self) -> str:
        return f"{self.name} @ {self.termin:%Y-%m-%d %H:%M}"


class WorkerLebenszeichen(models.Model):
    """Health-Endpoint und Monitoring sehen hier, ob ein Worker lebt (F4)."""

    name = models.CharField(max_length=100, unique=True)
    gestartet = models.DateTimeField(default=timezone.now)
    zuletzt = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return self.name
