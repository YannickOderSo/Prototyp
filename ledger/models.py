"""Spiegel der Daten aus dem Bestandstool. Lexware bleibt System of Record (ADR-001).

In der App gepflegt werden nur: Kundentyp, Mahnpausen, Notizen, Verzugshinweis-Kennzeichen.
Beträge, Nummern, Daten und Status kommen ausschließlich aus dem Abgleich.
"""

from decimal import Decimal

from django.db import models
from django.utils import timezone

from accounts.mandant import FirmaModel
from cockpit.felder import geldfeld


class Kundentyp(models.TextChoices):
    PRIVAT = "privat", "Privatkunde"
    UNTERNEHMER = "unternehmer", "Unternehmer"
    UNBEKANNT = "unbekannt", "unbekannt"


class Kontakt(FirmaModel):
    extern_id = models.CharField(max_length=100)
    name = models.CharField(max_length=250)
    email = models.EmailField(blank=True)
    kundennummer = models.CharField(max_length=50, blank=True)
    ist_unternehmen_extern = models.BooleanField(null=True, blank=True, help_text="Firma/Person laut Lexware (Hinweis)")
    archiviert = models.BooleanField(default=False)
    adresse = models.TextField(blank=True, help_text="Rechnungsadresse laut Lexware (für Mahnschreiben der App)")
    # in der App gepflegt
    kundentyp = models.CharField(max_length=20, choices=Kundentyp.choices, default=Kundentyp.UNBEKANNT)
    excel_nummer = models.CharField(max_length=50, blank=True, help_text="Kundennummer aus einem Excel-Import")
    mahnpause_bis = models.DateField(null=True, blank=True)
    notiz = models.TextField(blank=True)
    aktualisiert = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "Kontakte"
        constraints = [models.UniqueConstraint(fields=["firma", "extern_id"], name="kontakt_extern_eindeutig")]
        indexes = [models.Index(fields=["firma", "kundentyp"], name="kontakt_kundentyp_idx")]

    def __str__(self) -> str:
        return self.name


class Artikel(FirmaModel):
    extern_id = models.CharField(max_length=100)
    bezeichnung = models.CharField(max_length=250)
    einheit = models.CharField(max_length=50, blank=True)
    netto = geldfeld()
    steuersatz = models.DecimalField(max_digits=5, decimal_places=2)
    typ = models.CharField(max_length=10, choices=[("PRODUCT", "Produkt"), ("SERVICE", "Dienstleistung")])
    artikelnummer = models.CharField(max_length=50, blank=True)
    archiviert = models.BooleanField(default=False)
    aktualisiert = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "Artikel"
        constraints = [models.UniqueConstraint(fields=["firma", "extern_id"], name="artikel_extern_eindeutig")]

    def __str__(self) -> str:
        return self.bezeichnung


class Beleg(FirmaModel):
    class Art(models.TextChoices):
        RECHNUNG = "rechnung", "Rechnung"
        ANGEBOT = "angebot", "Angebot"
        ABSCHLAG = "abschlag", "Abschlagsrechnung"

    class Status(models.TextChoices):
        ENTWURF = "entwurf", "Entwurf"
        OFFEN = "offen", "offen"
        UEBERFAELLIG = "ueberfaellig", "überfällig"
        BEZAHLT = "bezahlt", "bezahlt"
        STORNIERT = "storniert", "storniert"
        # nur Angebote (M7-02)
        ANGENOMMEN = "angenommen", "angenommen"
        ABGELEHNT = "abgelehnt", "abgelehnt"

    OFFENE_STATUS = (Status.OFFEN, Status.UEBERFAELLIG)

    class Quelle(models.TextChoices):
        LEXWARE = "lexware", "Lexware"
        IMPORT = "import", "Import aus Excel"
        KOPIE = "kopie", "Rechnungskopie"  # ADR-011 Stufe 3: aus der Kopie einer Ausgangsrechnung

    extern_id = models.CharField(max_length=100)
    art = models.CharField(max_length=20, choices=Art.choices, default=Art.RECHNUNG)
    nummer = models.CharField(max_length=50, blank=True)
    belegdatum = models.DateField(null=True, blank=True)
    faellig_am = models.DateField(null=True, blank=True)
    gueltig_bis = models.DateField(null=True, blank=True, help_text="Nur Angebote: Ablaufdatum aus Lexware")
    kontakt = models.ForeignKey(Kontakt, null=True, blank=True, on_delete=models.SET_NULL, related_name="belege")
    kontakt_name = models.CharField(max_length=250, blank=True)
    brutto = geldfeld(default=Decimal("0.00"))
    offen = geldfeld(default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OFFEN)
    bezahlt_am = models.DateField(null=True, blank=True)
    aktualisiert_extern = models.DateTimeField(null=True, blank=True)
    zuletzt_abgeglichen = models.DateTimeField(default=timezone.now)
    # in der App gepflegt
    verzugshinweis_enthalten = models.BooleanField(
        null=True, blank=True, help_text="Leer: Firmeneinstellung gilt. Ja/Nein: manuell für diesen Beleg"
    )
    mahnpause_bis = models.DateField(null=True, blank=True)
    mahnstufe = models.PositiveSmallIntegerField(default=0, help_text="Höchste versendete Stufe (0 = keine)")
    # ADR-008: importierte Posten leben nur im Cockpit und sind vom Lexware-Abgleich ausgenommen
    quelle = models.CharField(max_length=10, choices=Quelle.choices, default=Quelle.LEXWARE)
    import_vorgang = models.ForeignKey(
        "datenimport.ImportVorgang", null=True, blank=True, on_delete=models.SET_NULL, related_name="belege"
    )

    @property
    def importiert(self) -> bool:
        return self.quelle == self.Quelle.IMPORT

    @property
    def lokal(self) -> bool:
        """Posten ohne Lexware (Excel-Import oder Rechnungskopie): Zahlstatus und Mahnschreiben in Belegfluss."""
        return self.quelle != self.Quelle.LEXWARE

    class Meta:
        verbose_name_plural = "Belege"
        constraints = [models.UniqueConstraint(fields=["firma", "extern_id"], name="beleg_extern_eindeutig")]
        indexes = [
            models.Index(fields=["firma", "status", "faellig_am"], name="beleg_offen_idx"),
            models.Index(fields=["firma", "kontakt"], name="beleg_kontakt_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_art_display()} {self.nummer}"

    @property
    def ist_offen(self) -> bool:
        return self.status in self.OFFENE_STATUS and self.offen > 0
