from django import forms

FAELLIGKEIT = [("", "alle"), ("ueberfaellig", "überfällig"), ("nicht_faellig", "noch nicht fällig")]
SORTIERUNG = [
    ("faellig", "Fälligkeit, älteste zuerst"),
    ("-faellig", "Fälligkeit, neueste zuerst"),
    ("-betrag", "Betrag, höchster zuerst"),
    ("betrag", "Betrag, niedrigster zuerst"),
    ("kunde", "Kunde A–Z"),
    ("-mahnstufe", "Mahnstufe, höchste zuerst"),
]
MAHNSTUFEN = [
    ("", "alle"),
    ("0", "noch nicht erinnert"),
    ("1", "Erinnerung versendet"),
    ("2", "1. Mahnung versendet"),
    ("3", "2. Mahnung versendet"),
]


class PostenFilterForm(forms.Form):
    kunde = forms.CharField(label="Kunde oder Rechnungsnummer", required=False, max_length=100)
    faelligkeit = forms.ChoiceField(label="Fälligkeit", choices=FAELLIGKEIT, required=False)
    faellig_von = forms.DateField(label="fällig ab", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    faellig_bis = forms.DateField(label="fällig bis", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    betrag_min = forms.DecimalField(label="Betrag ab (€)", required=False, min_value=0, decimal_places=2)
    betrag_max = forms.DecimalField(label="Betrag bis (€)", required=False, min_value=0, decimal_places=2)
    mahnstufe = forms.ChoiceField(label="Mahnstufe", choices=MAHNSTUFEN, required=False)
    sortierung = forms.ChoiceField(label="Sortierung", choices=SORTIERUNG, required=False)
