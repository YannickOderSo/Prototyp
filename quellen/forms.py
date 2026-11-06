from __future__ import annotations

from typing import Any

from django import forms

from .kopien import MAX_DATEI_BYTES

MAX_DATEIEN = 20


class MehrfachDatei(forms.ClearableFileInput):
    allow_multiple_selected = True


class MehrfachDateiFeld(forms.FileField):
    def clean(self, data: Any, initial: Any = None) -> Any:
        einzeln = super().clean
        if isinstance(data, list | tuple):
            return [einzeln(d, initial) for d in data]
        return [einzeln(data, initial)]


class KopienUploadForm(forms.Form):
    dateien = MehrfachDateiFeld(
        label="Rechnungen (PDF oder XML)",
        help_text="E-Rechnungen (ZUGFeRD, XRechnung) werden direkt gelesen; andere PDFs liest die KI vor und Sie "
        "bestätigen die Werte. Höchstens 20 Dateien, je 25 MB.",
        widget=MehrfachDatei(attrs={"accept": ".pdf,.xml"}),
    )

    def clean_dateien(self) -> list[Any]:
        dateien = self.cleaned_data["dateien"]
        if len(dateien) > MAX_DATEIEN:
            raise forms.ValidationError("Höchstens 20 Dateien auf einmal.")
        for datei in dateien:
            if datei.size > MAX_DATEI_BYTES:
                raise forms.ValidationError(f"„{datei.name}“ ist größer als 25 MB.")
        return list(dateien)


class PruefForm(forms.Form):
    """K3/K5: Werte einer Kopie prüfen und bestätigen. Beträge stehen auf der Rechnung, die KI setzt nichts fest."""

    ARTEN = [
        ("rechnung", "Rechnung"),
        ("abschlag", "Abschlagsrechnung"),
        ("gutschrift", "Gutschrift"),
        ("korrektur", "Rechnungskorrektur"),
    ]
    art = forms.ChoiceField(label="Art", choices=ARTEN)
    nummer = forms.CharField(label="Rechnungsnummer", max_length=50)
    belegdatum = forms.DateField(label="Rechnungsdatum", widget=forms.DateInput(attrs={"type": "date"}))
    faellig_am = forms.DateField(
        label="Fällig am",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Steht auf der Rechnung (Zahlungsziel).",
    )
    kaeufer_name = forms.CharField(label="Kunde", max_length=250)
    kaeufer_email = forms.EmailField(label="E-Mail des Kunden", required=False)
    kaeufer_anschrift = forms.CharField(
        label="Anschrift des Kunden", required=False, max_length=1000, widget=forms.Textarea(attrs={"rows": 3})
    )
    brutto = forms.DecimalField(
        label="Rechnungsbetrag brutto (€)", max_digits=12, decimal_places=2, min_value=0, localize=True
    )
    zahlbetrag = forms.DecimalField(
        label="Offener Betrag (€)",
        max_digits=12,
        decimal_places=2,
        min_value=0,
        localize=True,
        help_text="Zahlbetrag laut Rechnung, also abzüglich Anzahlungen.",
    )
    bezug = forms.CharField(
        label="Bezieht sich auf Rechnung", required=False, max_length=50, help_text="Nur bei Gutschrift und Korrektur."
    )

    def clean(self) -> dict[str, Any]:
        daten = super().clean() or {}
        art = daten.get("art")
        if art in ("rechnung", "abschlag", "korrektur") and not daten.get("faellig_am"):
            self.add_error("faellig_am", "Bitte die Fälligkeit von der Rechnung übernehmen.")
        if art == "gutschrift" and not daten.get("bezug"):
            self.add_error("bezug", "Bitte die Nummer der Rechnung angeben, die gutgeschrieben wird.")
        return daten

    def werte(self) -> dict[str, Any]:
        d = self.cleaned_data
        return {
            "art": d["art"],
            "nummer": d["nummer"].strip(),
            "belegdatum": d["belegdatum"].isoformat(),
            "faellig_am": d["faellig_am"].isoformat() if d.get("faellig_am") else "",
            "kaeufer_name": d["kaeufer_name"].strip(),
            "kaeufer_email": (d.get("kaeufer_email") or "").strip().lower(),
            "kaeufer_anschrift": d.get("kaeufer_anschrift") or "",
            "brutto": str(d["brutto"]),
            "zahlbetrag": str(d["zahlbetrag"]),
            "bezug": (d.get("bezug") or "").strip(),
            "waehrung": "EUR",
        }

    @classmethod
    def aus_kopie(cls, daten: dict[str, Any]) -> PruefForm:
        felder = {k: daten.get(k, "") for k in cls.base_fields}
        if "kaeufer_anschrift" not in daten and daten.get("kaeufer_name"):
            felder["kaeufer_anschrift"] = ""
        if felder.get("art") not in dict(cls.ARTEN):
            felder["art"] = "rechnung"
        return cls(initial=felder)
