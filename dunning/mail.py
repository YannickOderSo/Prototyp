"""Inhalt der Erinnerungs- und Mahnmails. Vorschau und Versand nutzen dieselbe Funktion (D10)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from email.utils import formataddr

from django.utils import timezone

from .mailversand import absender_adresse
from .models import Mahnvorschlag
from .recht import ZinsAbschnitt, ZinsErgebnis, zinstext
from .services import mahnplan_fuer
from .texte import STANDARD, ersetzen


def euro(betrag: Decimal) -> str:
    text = f"{betrag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"


def _datum(tag: date | None) -> str:
    return tag.strftime("%d.%m.%Y") if tag else "–"


@dataclass(frozen=True)
class MailInhalt:
    absender: str
    empfaenger: str
    reply_to: str
    bcc: str
    betreff: str
    text: str
    anhang_name: str


def neue_frist(vorschlag: Mahnvorschlag, versandtag: date) -> date | None:
    tage = mahnplan_fuer(vorschlag.firma).frist_fuer_stufe(vorschlag.stufe)
    return versandtag + timedelta(days=tage) if tage else None


def _zinsergebnis(vorschlag: Mahnvorschlag) -> ZinsErgebnis:
    abschnitte = tuple(
        ZinsAbschnitt(
            von=date.fromisoformat(a["von"]),
            bis=date.fromisoformat(a["bis"]),
            tage=int(a["tage"]),
            basiszins=Decimal(a["basiszins"]),
            zinssatz=Decimal(a["zinssatz"]),
            jahrestage=int(a["jahrestage"]),
            betrag=Decimal(a["betrag"]),
        )
        for a in vorschlag.zinsberechnung
    )
    aufschlag = abschnitte[0].zinssatz - abschnitte[0].basiszins if abschnitte else Decimal(0)
    return ZinsErgebnis(vorschlag.zinsen, abschnitte, grundlage=vorschlag.offen_betrag, aufschlag=aufschlag)


def zinsberechnung_text(vorschlag: Mahnvorschlag) -> str:
    return zinstext(_zinsergebnis(vorschlag)) if vorschlag.zinsen > 0 else ""


def anhang_name(vorschlag: Mahnvorschlag) -> str:
    art = "Rechnung" if vorschlag.stufe == 0 else ("Mahnung" if vorschlag.stufe == 1 else "2_Mahnung")
    nummer = "".join(ch for ch in vorschlag.beleg.nummer if ch.isalnum() or ch in "-_") or str(vorschlag.beleg_id)
    return f"{art}_{nummer}.pdf"


def inhalt(vorschlag: Mahnvorschlag, versandtag: date | None = None) -> MailInhalt:
    versandtag = versandtag or timezone.localdate()
    firma = vorschlag.firma
    beleg = vorschlag.beleg
    kontakt = beleg.kontakt
    plan = mahnplan_fuer(firma)
    standard_betreff, standard_text = STANDARD[vorschlag.stufe]
    betreff_vorlage = getattr(plan, f"betreff_{vorschlag.stufe}") or standard_betreff
    text_vorlage = getattr(plan, f"text_{vorschlag.stufe}") or standard_text
    frist = neue_frist(vorschlag, versandtag)
    zinsen = zinsberechnung_text(vorschlag)
    name = kontakt.name if kontakt else beleg.kontakt_name
    anrede = "Guten Tag" if (kontakt is None or kontakt.ist_unternehmen_extern is not False) else f"Guten Tag {name}"
    werte = {
        "kunde": name,
        "anrede": anrede,
        "rechnungsnummer": beleg.nummer,
        "rechnungsdatum": _datum(beleg.belegdatum),
        "faellig_am": _datum(beleg.faellig_am),
        "offen": euro(vorschlag.offen_betrag),
        "zinsen": euro(vorschlag.zinsen),
        "zinsberechnung": zinsen,
        "pauschale": euro(vorschlag.pauschale),
        "gesamt": euro(vorschlag.gesamt),
        "neue_frist": _datum(frist),
        "bankverbindung": firma.bankverbindung or "siehe Rechnung",
        "firma": firma.name,
        "signatur": firma.mahn_signatur or firma.name,
        "zinsen_zeile": (
            f"Verzugszinsen (§ 288 BGB, ab {_datum(vorschlag.verzugsbeginn + timedelta(days=1))}): "
            f"{euro(vorschlag.zinsen)}\nBerechnung:\n{zinsen}\n"
            if vorschlag.zinsen > 0 and vorschlag.verzugsbeginn
            else ""
        ),
        "pauschale_zeile": (
            f"Verzugspauschale (§ 288 Abs. 5 BGB): {euro(vorschlag.pauschale)}\n" if vorschlag.pauschale > 0 else ""
        ),
    }
    return MailInhalt(
        absender=formataddr((firma.email_absender or firma.name, absender_adresse(firma))),
        empfaenger=kontakt.email if kontakt else "",
        reply_to=firma.reply_to,
        bcc=firma.reply_to if plan.bcc_an_firma and firma.reply_to else "",
        betreff=ersetzen(betreff_vorlage, werte).replace("\n", " ").strip(),
        text=ersetzen(text_vorlage, werte).strip() + "\n",
        anhang_name=anhang_name(vorschlag),
    )
