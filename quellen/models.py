"""Rechnungskopien und Kontoauszüge (ADR-011 Stufe 3, Anforderungen K1–K9).

Gespeichert werden nur die gelesenen Felder, nie die Dateien selbst (Archiv bleibt beim Bestandstool, ADR-001).
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.mandant import FirmaModel


def _kopie_token() -> str:
    # Präfix „r“: nie gleich einem Belegpostfach-Token (nur Hex), damit die Weiche im Postfach eindeutig ist
    return "r" + secrets.token_hex(8)


def _in_12_monaten() -> object:
    return timezone.now() + timedelta(days=365)


class Kopieadresse(FirmaModel):
    """K1: Adresse für Kopien der eigenen Ausgangsrechnungen, z. B. belege+r<token>@domain. Nur erlaubte Absender."""

    token = models.CharField(max_length=32, unique=True, default=_kopie_token)
    aktiv = models.BooleanField(default=True)
    absender = models.JSONField(default=list, blank=True, help_text="Erlaubte Absender: Adressen oder @domain")
    erstellt = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "Kopie-Adressen"
        constraints = [models.UniqueConstraint(fields=["firma"], name="kopieadresse_je_firma")]

    def __str__(self) -> str:
        return f"Kopie-Adresse {self.firma_id}"


class Rechnungskopie(FirmaModel):
    """Eine eingegangene Kopie einer Ausgangsrechnung (Mail oder Hochladen) und was daraus wurde."""

    class Status(models.TextChoices):
        ANGELEGT = "angelegt", "übernommen"
        PRUEFUNG = "pruefung", "bitte prüfen"
        DOPPELT = "doppelt", "schon vorhanden"
        ABGELEHNT = "abgelehnt", "nicht lesbar"
        VERWORFEN = "verworfen", "verworfen"

    class Weg(models.TextChoices):
        MAIL = "mail", "per Mail"
        UPLOAD = "upload", "hochgeladen"

    weg = models.CharField(max_length=10, choices=Weg.choices, default=Weg.UPLOAD)
    message_id = models.CharField(max_length=300, blank=True)
    dateiname = models.CharField(max_length=200)
    format = models.CharField(max_length=20, blank=True, help_text="zugferd, xrechnung_cii, xrechnung_ubl oder pdf")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PRUEFUNG)
    daten = models.JSONField(default=dict, blank=True, help_text="Gelesene Felder (EN 16931) bzw. Vorschlag der KI")
    grund = models.TextField(blank=True, help_text="Warum geprüft werden muss oder warum abgelehnt")
    text = models.TextField(blank=True, help_text="Text eines PDF ohne E-Rechnung für die KI; nach Prüfung geleert")
    ki_gelesen = models.BooleanField(default=False)
    beleg = models.ForeignKey("ledger.Beleg", null=True, blank=True, on_delete=models.SET_NULL, related_name="kopien")
    erstellt = models.DateTimeField(default=timezone.now)
    erstellt_von = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    geprueft_von = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    geprueft_am = models.DateTimeField(null=True, blank=True)
    loeschen_ab = models.DateTimeField(default=_in_12_monaten)

    class Meta:
        verbose_name_plural = "Rechnungskopien"
        indexes = [models.Index(fields=["firma", "-erstellt"], name="rechnungskopie_firma_idx")]

    def __str__(self) -> str:
        return f"Rechnungskopie {self.daten.get('nummer') or self.dateiname}"

    @property
    def nummer(self) -> str:
        return str(self.daten.get("nummer") or "")


class Kontoauszug(FirmaModel):
    """K6: ein hochgeladener Kontoauszug. Die Datei selbst wird nicht gespeichert, nur Stand und Zählwerte."""

    dateiname = models.CharField(max_length=200)
    format = models.CharField(max_length=10, help_text="camt053, camt052 oder csv")
    konto = models.CharField(max_length=40, blank=True, help_text="IBAN gekürzt, z. B. DE89 •••• 3000")
    von = models.DateField(null=True, blank=True)
    bis = models.DateField(null=True, blank=True, help_text="Stand: letzter Buchungstag im Auszug")
    gutschriften = models.PositiveIntegerField(default=0)
    neu = models.PositiveIntegerField(default=0)
    doppelt = models.PositiveIntegerField(default=0)
    hochgeladen_von = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    erstellt = models.DateTimeField(default=timezone.now)
    loeschen_ab = models.DateTimeField(default=_in_12_monaten)

    class Meta:
        verbose_name_plural = "Kontoauszüge"
        indexes = [models.Index(fields=["firma", "-bis"], name="kontoauszug_firma_idx")]

    def __str__(self) -> str:
        return f"Kontoauszug {self.dateiname}"


class Zahlung(FirmaModel):
    """K6/K7: ein Zahlungseingang (nur Gutschriften). Zugeordnet wird erst, wenn ein Mensch bestätigt."""

    class Status(models.TextChoices):
        NEU = "neu", "zuzuordnen"
        ZUGEORDNET = "zugeordnet", "zugeordnet"
        IGNORIERT = "ignoriert", "ignoriert"

    kontoauszug = models.ForeignKey(Kontoauszug, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    schluessel = models.CharField(max_length=64, help_text="Hash gegen doppelt hochgeladene Umsätze")
    buchungsdatum = models.DateField()
    betrag = models.DecimalField(max_digits=12, decimal_places=2)
    waehrung = models.CharField(max_length=3, default="EUR")
    zahler = models.CharField(max_length=200, blank=True)
    zahler_konto = models.CharField(max_length=40, blank=True, help_text="IBAN gekürzt")
    verwendungszweck = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEU)
    vorschlag = models.ForeignKey("ledger.Beleg", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    vorschlag_grund = models.CharField(max_length=300, blank=True)
    beleg = models.ForeignKey(
        "ledger.Beleg", null=True, blank=True, on_delete=models.SET_NULL, related_name="zahlungseingaenge"
    )
    erledigt_von = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    erledigt_am = models.DateTimeField(null=True, blank=True)
    erstellt = models.DateTimeField(default=timezone.now)
    loeschen_ab = models.DateTimeField(default=_in_12_monaten)

    class Meta:
        verbose_name_plural = "Zahlungen"
        constraints = [models.UniqueConstraint(fields=["firma", "schluessel"], name="zahlung_einmal_je_firma")]
        indexes = [models.Index(fields=["firma", "status", "-buchungsdatum"], name="zahlung_firma_status_idx")]

    def __str__(self) -> str:
        return f"Zahlung {self.betrag} {self.buchungsdatum}"
