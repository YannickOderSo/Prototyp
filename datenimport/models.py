"""Import aus Excel und CSV (ADR-008, Anforderungen H1–H9).

Ein Importvorgang hält die gelesenen Zeilen, die Spaltenzuordnung, die Vorschau und das Ergebnis.
Die Datei selbst wird nicht gespeichert; die gelesenen Zeilen werden nach 7 Tagen gelöscht (H9),
Anzahlen und Ergebnis bleiben als Nachweis.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.mandant import FirmaModel


def _in_7_tagen() -> datetime:
    return timezone.now() + timedelta(days=7)


class ImportVorgang(FirmaModel):
    class Art(models.TextChoices):
        KUNDEN = "kunden", "Kunden"
        ARTIKEL = "artikel", "Artikel und Preise"
        POSTEN = "posten", "Offene Rechnungen"

    class Status(models.TextChoices):
        ZUORDNUNG = "zuordnung", "Spalten zuordnen"
        VORSCHAU = "vorschau", "Vorschau prüfen"
        FREIGEGEBEN = "freigegeben", "wird importiert"
        FERTIG = "fertig", "importiert"
        FEHLER = "fehler", "Fehler"
        VERWORFEN = "verworfen", "verworfen"

    art = models.CharField(max_length=20, choices=Art.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ZUORDNUNG)
    dateiname = models.CharField(max_length=255)
    blatt = models.CharField(max_length=100, blank=True)
    spalten = models.JSONField(default=list, blank=True, help_text="Überschriften der Kopfzeile")
    zeilen = models.JSONField(default=list, blank=True, help_text="Gelesene Zeilen als Text (nach 7 Tagen gelöscht)")
    zuordnung = models.JSONField(default=dict, blank=True, help_text="Feld → Spaltennummer")
    standardwerte = models.JSONField(default=dict, blank=True, help_text="z. B. Steuersatz für Zeilen ohne Angabe")
    kundentyp_uebernehmen = models.BooleanField(default=False)
    vorschau = models.JSONField(default=list, blank=True)
    ergebnis = models.JSONField(default=dict, blank=True)
    erstellt_von = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    erstellt = models.DateTimeField(default=timezone.now)
    freigegeben_von = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    freigegeben_am = models.DateTimeField(null=True, blank=True)
    loeschen_ab = models.DateTimeField(default=_in_7_tagen)
    zeilen_geloescht_am = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Importvorgang"
        verbose_name_plural = "Importvorgänge"
        indexes = [models.Index(fields=["firma", "-erstellt"], name="import_firma_idx")]

    def __str__(self) -> str:
        return f"Import {self.get_art_display()} {self.dateiname}"

    def anzahl(self, status: str) -> int:
        return sum(1 for z in self.vorschau if z.get("status") == status)
