from django import forms

from accounts.models import Firma


class FirmendatenForm(forms.ModelForm):
    class Meta:
        model = Firma
        fields = ["name", "strasse", "plz", "ort", "email_absender", "reply_to", "mahn_signatur", "bankverbindung"]
        help_texts = {
            "email_absender": "So erscheint der Absender in Erinnerungen und Mahnungen, z. B. „Malerbetrieb Muster“.",
            "reply_to": "Antworten Ihrer Kunden gehen an diese Adresse.",
            "bankverbindung": "Erscheint in jeder Mahnung, z. B. IBAN und Bank.",
        }
        widgets = {
            "mahn_signatur": forms.Textarea(attrs={"rows": 4}),
            "bankverbindung": forms.Textarea(attrs={"rows": 3}),
        }
