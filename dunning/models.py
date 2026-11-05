"""Mahnautomatik: Mahnplan je Firma, Basiszins-Tabelle, Vorschläge und Versände."""

from datetime import time
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.mandant import FirmaModel
from cockpit.felder import geldfeld, zinsfeld

# Harte Untergrenze zwischen zwei Stufen (Mahnlogik-und-Recht.md)
MINDESTABSTAND_TAGE = 7


class Wochentag(models.IntegerChoices):
    MONTAG = 0, "Montag"
    DIENSTAG = 1, "Dienstag"
    MITTWOCH = 2, "Mittwoch"
    DONNERSTAG = 3, "Donnerstag"
    FREITAG = 4, "Freitag"


class Mahnplan(FirmaModel):
    """Regeln je Firma (D1). Standard: Erinnerung 7, 1. Mahnung 21, 2. Mahnung 35 Tage nach Fälligkeit."""

    erinnerung_aktiv = models.BooleanField("Zahlungserinnerung (Stufe 0) verwenden", default=True)
    tage_erinnerung = models.PositiveSmallIntegerField("Erinnerung ab Tag nach Fälligkeit", default=7)
    tage_mahnung1 = models.PositiveSmallIntegerField("1. Mahnung ab Tag nach Fälligkeit", default=21)
    tage_mahnung2 = models.PositiveSmallIntegerField("2. Mahnung ab Tag nach Fälligkeit", default=35)
    abstand_tage = models.PositiveSmallIntegerField("Mindestabstand zur vorigen Stufe (Tage)", default=10)
    frist_mahnung1_tage = models.PositiveSmallIntegerField("Neue Zahlungsfrist 1. Mahnung (Tage)", default=10)
    frist_mahnung2_tage = models.PositiveSmallIntegerField("Neue Zahlungsfrist 2. Mahnung (Tage)", default=7)
    zinsen_aktiv = models.BooleanField("Verzugszinsen ausweisen (Stufe 1 und 2)", default=True)
    pauschale_aktiv = models.BooleanField("40-€-Pauschale bei Unternehmern", default=True)
    verzugshinweis_auf_rechnungen = models.BooleanField(
        "Unsere Rechnungen enthalten den Verzugshinweis für Privatkunden (§ 286 Abs. 3 BGB)", default=False
    )
    wochentag_freigabe = models.PositiveSmallIntegerField("Sammelfreigabe am", choices=Wochentag.choices, default=0)
    uhrzeit_freigabe = models.TimeField("Sammelfreigabe um", default=time(7, 0))
    bcc_an_firma = models.BooleanField("Kopie jeder Mahnung an die Antwortadresse der Firma", default=False)
    automatik_aktiv = models.BooleanField("Täglich Vorschläge erzeugen", default=True)
    betreff_0 = models.CharField(max_length=200, blank=True)
    text_0 = models.TextField(blank=True)
    betreff_1 = models.CharField(max_length=200, blank=True)
    text_1 = models.TextField(blank=True)
    betreff_2 = models.CharField(max_length=200, blank=True)
    text_2 = models.TextField(blank=True)
    geaendert = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "Mahnpläne"
        constraints = [models.UniqueConstraint(fields=["firma"], name="mahnplan_je_firma")]

    def __str__(self) -> str:
        return f"Mahnplan {self.firma_id}"

    def clean(self) -> None:
        fehler = {}
        if self.erinnerung_aktiv and self.tage_mahnung1 - self.tage_erinnerung < MINDESTABSTAND_TAGE:
            fehler["tage_mahnung1"] = (
                f"Zwischen Erinnerung und 1. Mahnung müssen mindestens {MINDESTABSTAND_TAGE} Tage liegen."
            )
        if self.tage_mahnung2 - self.tage_mahnung1 < MINDESTABSTAND_TAGE:
            fehler["tage_mahnung2"] = f"Zwischen 1. und 2. Mahnung müssen mindestens {MINDESTABSTAND_TAGE} Tage liegen."
        if self.abstand_tage < MINDESTABSTAND_TAGE:
            fehler["abstand_tage"] = f"Der Mindestabstand beträgt {MINDESTABSTAND_TAGE} Tage."
        if self.tage_erinnerung < 1:
            fehler["tage_erinnerung"] = "Erinnerungen frühestens einen Tag nach Fälligkeit."
        if fehler:
            raise ValidationError(fehler)

    def tage_fuer_stufe(self, stufe: int) -> int:
        return [self.tage_erinnerung, self.tage_mahnung1, self.tage_mahnung2][stufe]

    def frist_fuer_stufe(self, stufe: int) -> int | None:
        return {1: self.frist_mahnung1_tage, 2: self.frist_mahnung2_tage}.get(stufe)


class Basiszins(models.Model):
    """Basiszinssatz nach § 247 BGB in Prozent. Gepflegte Tabelle, halbjährlich (1.1. und 1.7.)."""

    gueltig_ab = models.DateField(unique=True)
    satz = zinsfeld("Satz in Prozent")
    quelle = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["gueltig_ab"]
        verbose_name_plural = "Basiszinssätze"

    def __str__(self) -> str:
        return f"{self.satz} % ab {self.gueltig_ab:%d.%m.%Y}"


class Mahnvorschlag(FirmaModel):
    class Status(models.TextChoices):
        VORGESCHLAGEN = "vorgeschlagen", "vorgeschlagen"
        FREIGEGEBEN = "freigegeben", "freigegeben"
        POST_BEREIT = "post_bereit", "Postversand bereit"
        VERSENDET = "versendet", "versendet"
        VERWORFEN = "verworfen", "verworfen"
        FEHLER = "fehler", "Fehler"

    class Stufe(models.IntegerChoices):
        ERINNERUNG = 0, "Zahlungserinnerung"
        MAHNUNG1 = 1, "1. Mahnung"
        MAHNUNG2 = 2, "2. Mahnung"

    beleg = models.ForeignKey("ledger.Beleg", on_delete=models.CASCADE, related_name="mahnvorschlaege")
    stufe = models.PositiveSmallIntegerField(choices=Stufe.choices)
    erstellt_am = models.DateTimeField(default=timezone.now)
    berechnet_am = models.DateField(default=timezone.localdate)
    faellig_seit_tagen = models.IntegerField(default=0)
    offen_betrag = geldfeld(default=Decimal("0.00"))
    zinsen = geldfeld(default=Decimal("0.00"))
    pauschale = geldfeld(default=Decimal("0.00"))
    gesamt = geldfeld(default=Decimal("0.00"))
    verzugsbeginn = models.DateField(null=True, blank=True)
    zinsberechnung = models.JSONField(default=list, blank=True)
    hinweise = models.JSONField(default=list, blank=True)
    versandart = models.CharField(max_length=10, choices=[("email", "E-Mail"), ("post", "Post")], default="email")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.VORGESCHLAGEN)
    freigegeben_von = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    freigegeben_am = models.DateTimeField(null=True, blank=True)
    verworfen_grund = models.CharField(max_length=300, blank=True)
    lexware_dunning_id = models.CharField(max_length=100, blank=True)
    pdf = models.BinaryField(null=True, blank=True, editable=False)
    pdf_name = models.CharField(max_length=200, blank=True)
    versendet_am = models.DateTimeField(null=True, blank=True)
    fehler = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "Mahnvorschläge"
        constraints = [models.UniqueConstraint(fields=["beleg", "stufe"], name="vorschlag_je_beleg_und_stufe")]
        indexes = [models.Index(fields=["firma", "status"], name="vorschlag_status_idx")]

    def __str__(self) -> str:
        return f"{self.get_stufe_display()} zu {self.beleg}"


class Versand(FirmaModel):
    """Eine versendete E-Mail (Erinnerung, Mahnung) mit Zustellstatus."""

    vorschlag = models.ForeignKey(
        Mahnvorschlag, null=True, blank=True, on_delete=models.PROTECT, related_name="versaende"
    )
    empfaenger = models.CharField(max_length=300)
    betreff = models.CharField(max_length=300)
    text = models.TextField()
    anhang_name = models.CharField(max_length=200, blank=True)
    message_id = models.CharField(max_length=300, blank=True, db_index=True)
    gesendet_am = models.DateTimeField(default=timezone.now)
    zustellfehler = models.TextField(blank=True)
    zustellfehler_am = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "Versände"

    def __str__(self) -> str:
        return f"{self.betreff} → {self.empfaenger}"


class SmtpZugang(FirmaModel):
    """Optional: eigenes SMTP der Firma. Ohne aktiven Zugang versendet die Plattform (EU-Anbieter)."""

    host = models.CharField("SMTP-Server", max_length=200)
    port = models.PositiveIntegerField("Port", default=587)
    benutzer = models.CharField("Benutzername", max_length=200, blank=True)
    passwort_verschluesselt = models.TextField(blank=True)
    starttls = models.BooleanField("STARTTLS", default=True)
    ssl = models.BooleanField("SSL/TLS direkt (Port 465)", default=False)
    absender_adresse = models.EmailField("Absenderadresse")
    aktiv = models.BooleanField("Eigenes SMTP verwenden", default=False)
    geprueft_am = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "SMTP-Zugang"
        verbose_name_plural = "SMTP-Zugänge"
        constraints = [models.UniqueConstraint(fields=["firma"], name="smtp_je_firma")]

    def __str__(self) -> str:
        return f"{self.host}:{self.port}"
