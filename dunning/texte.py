"""Standardtexte je Stufe (Mahnlogik-und-Recht.md, Textvorgaben) und sichere Platzhalter-Ersetzung.

Platzhalter in geschweiften Klammern, z. B. {rechnungsnummer}. Es wird nur ersetzt, was in der Liste
PLATZHALTER steht; Attributzugriffe wie in str.format gibt es bewusst nicht.
"""

import re

PLATZHALTER = {
    "kunde": "Name des Kunden",
    "anrede": "Anrede, z. B. „Guten Tag Frau Musterfrau“",
    "rechnungsnummer": "Rechnungsnummer",
    "rechnungsdatum": "Rechnungsdatum",
    "faellig_am": "ursprüngliche Fälligkeit",
    "offen": "offener Betrag",
    "zinsen": "Verzugszinsen",
    "zinsberechnung": "Berechnungsgrundlage der Zinsen",
    "pauschale": "Verzugspauschale",
    "gesamt": "Gesamtbetrag",
    "neue_frist": "neue Zahlungsfrist (Datum)",
    "bankverbindung": "Bankverbindung der Firma",
    "firma": "Name der Firma",
    "signatur": "Signatur der Firma",
}

GEGENSTANDSLOS = "Falls sich Ihre Zahlung mit diesem Schreiben überschnitten hat, betrachten Sie es als gegenstandslos."

STANDARD = {
    0: (
        "Zahlungserinnerung zu Rechnung {rechnungsnummer}",
        """{anrede},

sicher ist das nur ein Versehen: Zu unserer Rechnung {rechnungsnummer} vom {rechnungsdatum}, fällig am {faellig_am}, ist bei uns noch kein vollständiger Zahlungseingang verbucht. Offen sind {offen}.

Wir bitten Sie, den Betrag in den nächsten Tagen zu überweisen. Die Rechnung finden Sie zur Sicherheit noch einmal im Anhang.

Bankverbindung:
{bankverbindung}

"""
        + GEGENSTANDSLOS
        + """

Freundliche Grüße
{signatur}""",
    ),
    1: (
        "1. Mahnung zu Rechnung {rechnungsnummer}",
        """{anrede},

zu unserer Rechnung {rechnungsnummer} vom {rechnungsdatum}, ursprünglich fällig am {faellig_am}, konnten wir trotz unserer Zahlungserinnerung noch keinen vollständigen Zahlungseingang feststellen.

Offener Rechnungsbetrag: {offen}
{zinsen_zeile}{pauschale_zeile}Gesamtbetrag: {gesamt}

Bitte überweisen Sie den Gesamtbetrag bis zum {neue_frist}.

Bankverbindung:
{bankverbindung}

"""
        + GEGENSTANDSLOS
        + """

Freundliche Grüße
{signatur}""",
    ),
    2: (
        "2. Mahnung zu Rechnung {rechnungsnummer}",
        """{anrede},

unsere Rechnung {rechnungsnummer} vom {rechnungsdatum}, ursprünglich fällig am {faellig_am}, ist trotz Erinnerung und 1. Mahnung weiterhin nicht vollständig bezahlt.

Offener Rechnungsbetrag: {offen}
{zinsen_zeile}{pauschale_zeile}Gesamtbetrag: {gesamt}

Bitte überweisen Sie den Gesamtbetrag bis spätestens {neue_frist}. Geht bis dahin keine Zahlung ein, behalten wir uns vor, die Forderung im gerichtlichen Mahnverfahren geltend zu machen.

Bankverbindung:
{bankverbindung}

"""
        + GEGENSTANDSLOS
        + """

Freundliche Grüße
{signatur}""",
    ),
}

# Zusätzliche Platzhalter, die nur die Standardtexte nutzen (Zeilen entfallen, wenn kein Betrag anfällt)
INTERN = {"zinsen_zeile", "pauschale_zeile"}

_MUSTER = re.compile(r"\{(\w+)\}")


def ersetzen(vorlage: str, werte: dict[str, str]) -> str:
    erlaubt = set(PLATZHALTER) | INTERN
    return _MUSTER.sub(lambda m: werte.get(m.group(1), "") if m.group(1) in erlaubt else m.group(0), vorlage)


def unbekannte_platzhalter(vorlage: str) -> list[str]:
    erlaubt = set(PLATZHALTER) | INTERN
    return sorted({m.group(1) for m in _MUSTER.finditer(vorlage) if m.group(1) not in erlaubt})


# ADR-009: Erinnerung an ein Angebot kurz vor Ablauf (eigene Platzhalter)
PLATZHALTER_ANGEBOT = {
    "kunde": "Name des Kunden",
    "anrede": "Anrede",
    "angebotsnummer": "Angebotsnummer",
    "angebotsdatum": "Angebotsdatum",
    "gueltig_bis": "Ablaufdatum des Angebots",
    "betrag": "Angebotsbetrag (brutto)",
    "firma": "Name der Firma",
    "signatur": "Signatur der Firma",
}

ANGEBOT_STANDARD = (
    "Unser Angebot {angebotsnummer}: Haben Sie noch Fragen?",
    """{anrede},

vor einiger Zeit haben wir Ihnen unser Angebot {angebotsnummer} vom {angebotsdatum} geschickt. Es ist noch bis zum {gueltig_bis} gültig.

Haben Sie Fragen oder möchten Sie etwas anpassen? Antworten Sie einfach auf diese Mail. Wir freuen uns über eine kurze Rückmeldung, auch wenn das Angebot nicht passt.

Das Angebot finden Sie zur Sicherheit noch einmal im Anhang.

Freundliche Grüße
{signatur}""",
)


def ersetzen_angebot(vorlage: str, werte: dict[str, str]) -> str:
    return _MUSTER.sub(
        lambda m: werte.get(m.group(1), "") if m.group(1) in PLATZHALTER_ANGEBOT else m.group(0), vorlage
    )


def unbekannte_platzhalter_angebot(vorlage: str) -> list[str]:
    return sorted({m.group(1) for m in _MUSTER.finditer(vorlage) if m.group(1) not in PLATZHALTER_ANGEBOT})
