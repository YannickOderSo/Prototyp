"""Fabriken für den generischen IDOR-Test. Jede Fabrik legt ein Objekt für die übergebene Firma an
und liefert die URL-Parameter. Neue Views mit IDs MÜSSEN hier eingetragen werden."""

from collections.abc import Callable

Fabrik = Callable[..., dict]


def _kontakt(firma, nutzer=None):
    from ledger.models import Kontakt

    k = Kontakt.objects.create(firma=firma, extern_id=f"idor-{firma.pk}-{Kontakt.objects.count()}", name="IDOR-Test")
    return {"pk": k.pk}


def _beleg(firma, nutzer=None):
    from ledger.models import Beleg

    b = Beleg.objects.create(firma=firma, extern_id=f"idor-beleg-{Beleg.objects.count()}", nummer="IDOR", offen=10)
    return {"pk": b.pk}


def _vorschlag(firma, nutzer=None, **extra):
    from dunning.models import Mahnvorschlag
    from ledger.models import Beleg, Kontakt

    n = Beleg.objects.count()
    k = Kontakt.objects.create(
        firma=firma, extern_id=f"idor-v-{n}", name="IDOR", kundentyp="unternehmer", email="a@b.example"
    )
    b = Beleg.objects.create(firma=firma, extern_id=f"idor-b-{n}", nummer=f"I{n}", kontakt=k, offen=10, status="offen")
    v = Mahnvorschlag.objects.create(firma=firma, beleg=b, stufe=0, pdf=b"%PDF-", **extra)
    return {"pk": v.pk}


def _erfassung(firma, nutzer=None, **extra):
    from capture.models import Erfassung

    e = Erfassung.objects.create(firma=firma, kanal="upload", notiz="IDOR", **extra)
    return {"pk": e.pk}


def _import(firma, nutzer=None):
    from datenimport.models import ImportVorgang

    v = ImportVorgang.objects.create(firma=firma, art="kunden", dateiname="idor.csv", spalten=["Firma"], zeilen=[["X"]])
    return {"pk": v.pk}


def _angebotserinnerung(firma, nutzer=None):
    from dunning.models import Angebotserinnerung
    from ledger.models import Beleg

    n = Beleg.objects.count()
    b = Beleg.objects.create(firma=firma, extern_id=f"idor-q-{n}", art="angebot", nummer=f"Q{n}", status="offen")
    return {"pk": Angebotserinnerung.objects.create(firma=firma, beleg=b).pk}


FAELLE: dict[str, Fabrik] = {
    "dunning:angebot_verwerfen": _angebotserinnerung,
    "dunning:angebot_vorschau": _angebotserinnerung,
    "datenimport:vorgang": _import,
    "datenimport:zuordnung": _import,
    "datenimport:freigeben": _import,
    "datenimport:verwerfen": _import,
    "datenimport:fortsetzen": _import,
    "datenimport:zahlung": _beleg,
    "capture:detail": _erfassung,
    "capture:neuversuch": _erfassung,
    "capture:transkript": _erfassung,
    "capture:pruefen": _erfassung,
    "capture:verwerfen": _erfassung,
    "capture:freigeben": _erfassung,
    "dunning:vorschau": _vorschlag,
    "dunning:verwerfen": _vorschlag,
    "dunning:neuversuch": _vorschlag,
    "dunning:pdf": _vorschlag,
    "dunning:post_versendet": _vorschlag,
    "ledger:kunde": _kontakt,
    "ledger:kundentyp_setzen": _kontakt,
    "ledger:kontakt_pause": _kontakt,
    "ledger:beleg": _beleg,
    "ledger:beleg_pause": _beleg,
    "ledger:beleg_verzugshinweis": _beleg,
}

# URLs mit Parametern, die keine Objekt-IDs einer Firma sind (mit Begründung)
AUSNAHMEN: dict[str, str] = {
    "web:rechtstext": "öffentliche Rechtstexte, Slug statt ID",
    "datenimport:vorlage": "leere Importvorlage je Art, enthält keine Firmendaten",
    "accounts:team_annehmen": "geheimes Einladungs-Token, gilt nur für die eingeladene E-Mail-Adresse",
    "accounts:password_reset_confirm": "Django-Token für Passwort-Reset, an Nutzer gebunden",
    "hooks:zustellung": "Webhook des Mailanbieters; geheimes Token aus der Umgebung, ändert nur Versände mit passender Message-ID",
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
