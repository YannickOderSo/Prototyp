from django import forms


class SchluesselForm(forms.Form):
    schluessel = forms.CharField(
        label="Lexware-API-Schlüssel",
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}),
        help_text=(
            "Den Schlüssel erzeugen Sie in Lexware Office unter "
            '<a href="https://app.lexware.de/addons/public-api" rel="noopener" target="_blank">'
            "Erweiterungen → Public API</a>. "
            "Die Public API erfordert den Tarif XL."
        ),
        max_length=200,
    )
