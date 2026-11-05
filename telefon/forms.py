from django import forms

from .models import Telefonassistent


class EinstellungForm(forms.ModelForm):
    class Meta:
        model = Telefonassistent
        fields = ["aktiv", "begruessung", "benachrichtigen"]
        widgets = {"begruessung": forms.TextInput(attrs={"placeholder": "Guten Tag, Sie sind verbunden mit …"})}


class ErledigtForm(forms.Form):
    notiz = forms.CharField(
        label="Interne Notiz (optional)",
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "z. B. zurückgerufen, Termin in Lexware angelegt"}),
    )
