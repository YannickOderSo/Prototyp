from django import forms

from .lesen import MAX_BYTES
from .models import ImportVorgang

ERKLAERUNG = {
    "kunden": "Werden nach Ihrer Freigabe in Lexware angelegt und erscheinen danach in Belegfluss.",
    "artikel": "Werden nach Ihrer Freigabe in Lexware angelegt und stehen danach für Angebote zur Verfügung.",
    "posten": "Alte offene Rechnungen werden nur in Belegfluss geführt und gemahnt, nie in Lexware gebucht.",
}
# Ohne Lexware (M9-08): nichts verlässt Belegfluss
ERKLAERUNG_OHNE_LEXWARE = {
    "kunden": "Werden nach Ihrer Freigabe nur in Belegfluss angelegt (ohne Lexware).",
    "artikel": "Nur mit Lexware möglich: Artikel dienen den Entwürfen, die nach Lexware übertragen werden.",
    "posten": "Alte offene Rechnungen werden nur in Belegfluss geführt und gemahnt. Unbekannte Kunden werden "
    "dabei mit angelegt.",
}


class UploadForm(forms.Form):
    art = forms.ChoiceField(label="Was möchten Sie importieren?", choices=ImportVorgang.Art.choices)
    datei = forms.FileField(
        label="Datei (Excel .xlsx oder CSV)",
        help_text="Erste Zeile mit Überschriften. Höchstens 5.000 Zeilen und 10 MB.",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx,.csv,.txt"}),
    )
    blatt = forms.CharField(
        label="Tabellenblatt (optional)",
        required=False,
        max_length=100,
        help_text="Leer lassen für das erste Blatt.",
    )

    def clean_datei(self):  # type: ignore[no-untyped-def]
        datei = self.cleaned_data["datei"]
        if datei.size > MAX_BYTES:
            raise forms.ValidationError("Die Datei ist größer als 10 MB.")
        return datei


class ZahlungForm(forms.Form):
    """H7: Zahlstatus importierter Posten im Cockpit pflegen."""

    bezahlt_am = forms.DateField(
        label="Vollständig bezahlt am", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    offen = forms.DecimalField(
        label="oder: neuer offener Betrag (€)",
        required=False,
        min_value=0,
        max_digits=12,
        decimal_places=2,
        localize=True,
        help_text="Bei einer Teilzahlung den Betrag eintragen, der noch offen ist.",
    )

    def clean(self):  # type: ignore[no-untyped-def]
        daten = super().clean()
        if bool(daten.get("bezahlt_am")) == (daten.get("offen") is not None):
            raise forms.ValidationError("Bitte entweder das Zahldatum oder den neuen offenen Betrag angeben.")
        return daten
