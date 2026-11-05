"""Verbindung einer Firma zu ihrem Bestandstool und empfangene Webhook-Ereignisse."""

import secrets

from django.db import models
from django.utils import timezone

from accounts.mandant import FirmaModel


def _webhook_token() -> str:
    return secrets.token_urlsafe(24)


class Verbindung(FirmaModel):
    class Typ(models.TextChoices):
        LEXWARE = "lexware", "Lexware Office"
        SEVDESK = "sevdesk", "sevdesk"

    class Status(models.TextChoices):
        AKTIV = "aktiv", "verbunden"
        FEHLER = "fehler", "Fehler"
        GETRENNT = "getrennt", "getrennt"

    typ = models.CharField(max_length=20, choices=Typ.choices, default=Typ.LEXWARE)
    schluessel_verschluesselt = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AKTIV)
    firmenname_extern = models.CharField(max_length=200, blank=True)
    organisation_id = models.CharField(max_length=100, blank=True)
    steuerart = models.CharField(max_length=20, default="net")
    kleinunternehmer = models.BooleanField(default=False)
    letzter_abgleich = models.DateTimeField(null=True, blank=True)
    erstimport_fertig = models.DateTimeField(null=True, blank=True)
    webhook_ids = models.JSONField(default=list, blank=True)
    webhook_token = models.CharField(max_length=64, unique=True, default=_webhook_token)
    fehler = models.TextField(blank=True)
    erstellt = models.DateTimeField(default=timezone.now)
    getrennt_am = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "Verbindungen"
        constraints = [models.UniqueConstraint(fields=["firma", "typ"], name="verbindung_je_typ")]

    def __str__(self) -> str:
        return f"{self.get_typ_display()} ({self.get_status_display()})"

    @property
    def aktiv(self) -> bool:
        return self.status == self.Status.AKTIV and bool(self.schluessel_verschluesselt)
