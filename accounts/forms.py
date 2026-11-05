from django import forms
from django.contrib.auth import password_validation

from web.rechtstexte import zustimmungspflichtig

from .models import Nutzer, Rolle


class RegistrierungsForm(forms.Form):
    einladungscode = forms.CharField(label="Einladungscode", max_length=40)
    firmenname = forms.CharField(label="Name Ihres Betriebs", max_length=200)
    name = forms.CharField(label="Ihr Name", max_length=150)
    email = forms.EmailField(label="E-Mail-Adresse")
    passwort = forms.CharField(label="Passwort", widget=forms.PasswordInput, strip=False)
    passwort2 = forms.CharField(label="Passwort wiederholen", widget=forms.PasswordInput, strip=False)

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        for text in zustimmungspflichtig():
            self.fields[f"zustimmung_{text.slug}"] = forms.BooleanField(
                label=f"Ich stimme {text.titel} (Version {text.version}) zu.", required=True
            )

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].lower()
        if Nutzer.objects.filter(email=email).exists():
            raise forms.ValidationError("Zu dieser E-Mail-Adresse gibt es bereits ein Konto. Bitte melden Sie sich an.")
        return email

    def clean(self) -> dict[str, object]:
        daten = super().clean() or {}
        if daten.get("passwort") and daten.get("passwort") != daten.get("passwort2"):
            self.add_error("passwort2", "Die Passwörter stimmen nicht überein.")
        elif daten.get("passwort"):
            try:
                password_validation.validate_password(str(daten["passwort"]), Nutzer(email=daten.get("email", "")))
            except forms.ValidationError as fehler:
                self.add_error("passwort", fehler)
        return daten


class AnmeldeForm(forms.Form):
    email = forms.EmailField(label="E-Mail-Adresse")
    passwort = forms.CharField(label="Passwort", widget=forms.PasswordInput, strip=False)


class TeamEinladungsForm(forms.Form):
    email = forms.EmailField(label="E-Mail-Adresse")
    rolle = forms.ChoiceField(label="Rolle", choices=Rolle.choices, initial=Rolle.MITARBEITER)


class NeuesKontoForm(forms.Form):
    name = forms.CharField(label="Ihr Name", max_length=150)
    passwort = forms.CharField(label="Passwort", widget=forms.PasswordInput, strip=False)
    passwort2 = forms.CharField(label="Passwort wiederholen", widget=forms.PasswordInput, strip=False)

    def __init__(self, *args: object, email: str = "", **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.email = email
        for text in zustimmungspflichtig():
            self.fields[f"zustimmung_{text.slug}"] = forms.BooleanField(
                label=f"Ich stimme {text.titel} (Version {text.version}) zu.", required=True
            )

    def clean(self) -> dict[str, object]:
        daten = super().clean() or {}
        if daten.get("passwort") and daten.get("passwort") != daten.get("passwort2"):
            self.add_error("passwort2", "Die Passwörter stimmen nicht überein.")
        elif daten.get("passwort"):
            try:
                password_validation.validate_password(str(daten["passwort"]), Nutzer(email=self.email))
            except forms.ValidationError as fehler:
                self.add_error("passwort", fehler)
        return daten


class ProfilForm(forms.ModelForm):
    """Name und Avatar (I5). E-Mail und Passwort ändern sich über eigene, abgesicherte Wege."""

    class Meta:
        model = Nutzer
        fields = ["name", "avatar_symbol", "avatar_farbe"]
        labels = {"name": "Ihr Name", "avatar_symbol": "Ihr Symbol", "avatar_farbe": "Farbe"}
        widgets = {"avatar_symbol": forms.RadioSelect, "avatar_farbe": forms.RadioSelect}
