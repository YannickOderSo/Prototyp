"""Konten: Nutzer (E-Mail als Login), Firma, Mitgliedschaft mit Rollen."""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class NutzerManager(BaseUserManager["Nutzer"]):
    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **extra: object) -> "Nutzer":
        if not email:
            raise ValueError("E-Mail-Adresse fehlt")
        nutzer = self.model(email=self.normalize_email(email).lower(), **extra)
        nutzer.set_password(password)
        nutzer.save(using=self._db)
        return nutzer

    def create_superuser(self, email: str, password: str | None = None, **extra: object) -> "Nutzer":
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra)


class Nutzer(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField("E-Mail", unique=True)
    name = models.CharField("Name", max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    erstellt = models.DateTimeField(default=timezone.now)

    objects = NutzerManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "Nutzer"
        verbose_name_plural = "Nutzer"

    def __str__(self) -> str:
        return self.email


class Firma(models.Model):
    """Mandant. Alle fachlichen Daten hängen an genau einer Firma."""

    name = models.CharField("Firmenname", max_length=200)
    strasse = models.CharField("Straße", max_length=200, blank=True)
    plz = models.CharField("PLZ", max_length=10, blank=True)
    ort = models.CharField("Ort", max_length=100, blank=True)
    email_absender = models.CharField("Absendername für Mails", max_length=200, blank=True)
    reply_to = models.EmailField("Antwortadresse (Reply-To)", blank=True)
    mahn_signatur = models.TextField("Signatur unter Erinnerungen und Mahnungen", blank=True)
    bankverbindung = models.TextField("Bankverbindung für Mahnungen", blank=True)
    zeitzone = models.CharField(max_length=50, default="Europe/Berlin")
    aktiv = models.BooleanField(default=True)
    erstellt = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Firma"
        verbose_name_plural = "Firmen"

    def __str__(self) -> str:
        return self.name
