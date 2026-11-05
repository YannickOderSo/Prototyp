"""Fabriken für den generischen IDOR-Test. Jede Fabrik legt ein Objekt für die übergebene Firma an
und liefert die URL-Parameter. Neue Views mit IDs MÜSSEN hier eingetragen werden."""

from collections.abc import Callable

Fabrik = Callable[..., dict]


def _kontakt(firma, nutzer=None):
    from ledger.models import Kontakt

    k = Kontakt.objects.create(firma=firma, extern_id=f"idor-{firma.pk}-{Kontakt.objects.count()}", name="IDOR-Test")
    return {"pk": k.pk}


FAELLE: dict[str, Fabrik] = {
    "ledger:kunde": _kontakt,
    "ledger:kundentyp_setzen": _kontakt,
}

# URLs mit Parametern, die keine Objekt-IDs einer Firma sind (mit Begründung)
AUSNAHMEN: dict[str, str] = {
    "web:rechtstext": "öffentliche Rechtstexte, Slug statt ID",
    "accounts:team_annehmen": "geheimes Einladungs-Token, gilt nur für die eingeladene E-Mail-Adresse",
    "accounts:password_reset_confirm": "Django-Token für Passwort-Reset, an Nutzer gebunden",
    "hooks:lexware": "Webhook ohne Login; geheimes Token je Verbindung plus RSA-Signatur und Organisations-ID",
}


def beispielmodelle() -> list[tuple[type, Callable]]:
    """Modelle mit FirmaManager und je eine Fabrik (für den Manager-Test)."""
    from connectors.models import Verbindung
    from ledger.models import Beleg, Kontakt

    return [
        (Verbindung, lambda firma: Verbindung.objects.create(firma=firma)),
        (Kontakt, lambda firma: Kontakt.objects.create(firma=firma, extern_id=f"m{firma.pk}", name="M")),
        (Beleg, lambda firma: Beleg.objects.create(firma=firma, extern_id=f"b{firma.pk}")),
    ]
