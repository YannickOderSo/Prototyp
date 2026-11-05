from django import forms

from .models import Mahnplan, SmtpZugang
from .texte import PLATZHALTER, unbekannte_platzhalter


class MahnplanForm(forms.ModelForm):
    class Meta:
        model = Mahnplan
        fields = [
            "automatik_aktiv",
            "erinnerung_aktiv",
            "tage_erinnerung",
            "tage_mahnung1",
            "tage_mahnung2",
            "abstand_tage",
            "frist_mahnung1_tage",
            "frist_mahnung2_tage",
            "zinsen_aktiv",
            "pauschale_aktiv",
            "verzugshinweis_auf_rechnungen",
            "wochentag_freigabe",
            "uhrzeit_freigabe",
            "bcc_an_firma",
            "betreff_0",
            "text_0",
            "betreff_1",
            "text_1",
            "betreff_2",
            "text_2",
        ]
        widgets = {
            "uhrzeit_freigabe": forms.TimeInput(attrs={"type": "time"}),
            "text_0": forms.Textarea(attrs={"rows": 10}),
            "text_1": forms.Textarea(attrs={"rows": 12}),
            "text_2": forms.Textarea(attrs={"rows": 12}),
        }
        help_texts = {
            "betreff_0": "Leer lassen für den Standardtext.",
            "text_0": "Leer lassen für den Standardtext. Platzhalter: " + ", ".join("{" + p + "}" for p in PLATZHALTER),
            "verzugshinweis_auf_rechnungen": (
                "Nur ankreuzen, wenn auf jeder Rechnung an Privatkunden steht, dass sie 30 Tage nach Fälligkeit und "
                "Zugang ohne weitere Mahnung in Verzug kommen."
            ),
        }

    def clean(self) -> dict[str, object]:
        daten = super().clean() or {}
        for feld in ("betreff_0", "text_0", "betreff_1", "text_1", "betreff_2", "text_2"):
            unbekannt = unbekannte_platzhalter(str(daten.get(feld) or ""))
            if unbekannt:
                self.add_error(feld, "Unbekannte Platzhalter: " + ", ".join("{" + u + "}" for u in unbekannt))
        return daten


class SmtpForm(forms.ModelForm):
    passwort = forms.CharField(
        label="Passwort",
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Leer lassen, um das gespeicherte Passwort zu behalten.",
    )

    class Meta:
        model = SmtpZugang
        fields = ["aktiv", "host", "port", "benutzer", "starttls", "ssl", "absender_adresse"]
        help_texts = {
            "aktiv": "Ohne eigenes SMTP versendet Belegfluss über seinen EU-Mailanbieter mit Ihrem Namen.",
            "absender_adresse": "Diese Adresse muss Ihr SMTP-Server als Absender erlauben (SPF/DKIM Ihrer Domain).",
        }
