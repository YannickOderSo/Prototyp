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


class Rolle(models.TextChoices):
    INHABER = "inhaber", "Inhaber"
    FREIGEBER = "freigeber", "Freigeber"
    MITARBEITER = "mitarbeiter", "Mitarbeiter"


ROLLEN_MIT_FREIGABE = {Rolle.INHABER, Rolle.FREIGEBER}


class Mitgliedschaft(models.Model):
    """Ein Nutzer kann mehreren Firmen angehören, je Firma mit genau einer Rolle (A3)."""

    nutzer = models.ForeignKey(Nutzer, on_delete=models.CASCADE, related_name="mitgliedschaften")
    firma = models.ForeignKey(Firma, on_delete=models.CASCADE, related_name="mitgliedschaften")
    rolle = models.CharField(max_length=20, choices=Rolle.choices)
    erstellt = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["nutzer", "firma"], name="mitgliedschaft_einmal")]
        verbose_name_plural = "Mitgliedschaften"

    def __str__(self) -> str:
        return f"{self.nutzer} @ {self.firma} ({self.rolle})"

    @property
    def darf_freigeben(self) -> bool:
        return self.rolle in ROLLEN_MIT_FREIGABE

    @property
    def ist_inhaber(self) -> bool:
        return self.rolle == Rolle.INHABER


class Einladung(models.Model):
    """Einladungscode für die geschlossene Beta (A1). Gespeichert wird nur der Hash, Code ist einmal verwendbar."""

    code_hash = models.CharField(max_length=64, unique=True)
    notiz = models.CharField(max_length=200, blank=True)
    erstellt_von = models.ForeignKey(Nutzer, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    erstellt = models.DateTimeField(default=timezone.now)
    gueltig_bis = models.DateTimeField(null=True, blank=True)
    verwendet_am = models.DateTimeField(null=True, blank=True)
    verwendet_von = models.ForeignKey(Firma, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name_plural = "Einladungen"

    def __str__(self) -> str:
        return f"Einladung {self.code_hash[:8]}…"


class TeamEinladung(models.Model):
    """Inhaber lädt eine Person mit Rolle in die Firma ein. Link per Mail, Token nur als Hash gespeichert."""

    firma = models.ForeignKey(Firma, on_delete=models.CASCADE, related_name="team_einladungen")
    email = models.EmailField()
    rolle = models.CharField(max_length=20, choices=Rolle.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    erstellt_von = models.ForeignKey(Nutzer, on_delete=models.CASCADE, related_name="+")
    erstellt = models.DateTimeField(default=timezone.now)
    gueltig_bis = models.DateTimeField()
    angenommen_am = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.email} → {self.firma} ({self.rolle})"


class Zustimmung(models.Model):
    """Zustimmung zu einem Rechtstext in einer bestimmten Version (F5)."""

    nutzer = models.ForeignKey(Nutzer, on_delete=models.CASCADE, related_name="zustimmungen")
    dokument = models.CharField(max_length=50)
    version = models.CharField(max_length=50)
    zeit = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"{self.nutzer} → {self.dokument} {self.version}"
