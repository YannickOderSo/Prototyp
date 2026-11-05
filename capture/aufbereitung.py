"""Textaufbereitung je Dateiart (M3-04): PDF-Text, CSV-Zeiterfassung, Mail, Notiz.

Zeiterfassungen werden hier deterministisch verdichtet, damit das Sprachmodell keine Zahlen addieren muss.
"""

from __future__ import annotations

import csv
import email
import email.policy
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from email.message import EmailMessage

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_ZEICHEN_JE_QUELLE = 15000


@dataclass
class Quelle:
    art: str  # pdf, zeiterfassung, mail, notiz
    name: str
    herkunft: str  # gesprochen, foto, mail, zeiterfassung, notiz (Schema der Extraktion)
    text: str
    stunden: list[dict[str, str]] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)

    def als_dict(self) -> dict[str, object]:
        return {
            "art": self.art,
            "name": self.name,
            "herkunft": self.herkunft,
            "text": self.text,
            "stunden": self.stunden,
            "hinweise": self.hinweise,
        }


def text_dekodieren(daten: bytes) -> str:
    for kodierung in ("utf-8-sig", "cp1252"):
        try:
            return daten.decode(kodierung)
        except UnicodeDecodeError:
            continue
    return daten.decode("utf-8", errors="replace")


def _kappen(text: str) -> tuple[str, list[str]]:
    text = text.strip()
    if len(text) > MAX_ZEICHEN_JE_QUELLE:
        return text[:MAX_ZEICHEN_JE_QUELLE], ["Der Text war sehr lang und wurde gekürzt."]
    return text, []


# ------------------------------------------------------------------ PDF
def pdf(name: str, daten: bytes) -> Quelle:
    try:
        leser = PdfReader(io.BytesIO(daten))
        if leser.is_encrypted:
            return Quelle(
                "pdf", name, "notiz", "", hinweise=[f"„{name}“ ist verschlüsselt und konnte nicht gelesen werden."]
            )
        seiten = [seite.extract_text() or "" for seite in leser.pages[:50]]
    except (PdfReadError, ValueError, KeyError, TypeError):
        return Quelle("pdf", name, "notiz", "", hinweise=[f"„{name}“ konnte nicht gelesen werden."])
    text, hinweise = _kappen("\n".join(seiten))
    if not text:
        hinweise.append(f"„{name}“ enthält keinen lesbaren Text (eingescannt?). Bitte als Foto hochladen.")
    return Quelle("pdf", name, "notiz", text, hinweise=hinweise)


# ------------------------------------------------------------------ CSV-Zeiterfassung
# Angelehnt an belegfluss/quellen.py (Lukas Welker, Nutzung freigegeben am 2026-11-05):
# Spaltennamen gängiger Zeiterfassungs-Exporte (Clockify, Toggl, Harvest), klein geschrieben.
SPALTEN = {
    "kunde": ["client", "kunde", "customer"],
    "projekt": ["project", "projekt"],
    "stunden": ["duration (decimal)", "hours", "stunden", "dauer (dezimal)"],
    "dauer": ["duration (h)", "duration", "dauer"],
    "datum": ["start date", "date", "datum", "spent date"],
}
# Eigene Ergänzungen
SPALTEN["stunden"] += ["stunden (dezimal)", "zeit (h)"]
SPALTEN["dauer"] += ["zeit"]


def _spalte(zeile: dict[str, str | None], art: str) -> str:
    klein = {str(k).strip().lower(): (v or "") for k, v in zeile.items() if k}
    for name in SPALTEN[art]:
        if name in klein:
            return klein[name].strip()
    return ""


def stunden_lesen(wert: str) -> Decimal:
    """„4,5“, „4.5“, „1:30“ und „01:30:00“ → Stunden als Decimal. Leer → 0. Ungültig → ValueError."""
    wert = wert.strip()
    if not wert:
        return Decimal(0)
    if ":" in wert:
        teile = wert.split(":")
        if len(teile) > 3 or not all(t.isdigit() for t in teile):
            raise ValueError(wert)
        h, m, s = ([int(t) for t in teile] + [0, 0])[:3]
        return Decimal(h) + Decimal(m) / 60 + Decimal(s) / 3600
    normal = wert.replace(" ", "")
    if "," in normal:
        normal = normal.replace(".", "").replace(",", ".")
    try:
        ergebnis = Decimal(normal)
    except InvalidOperation as fehler:
        raise ValueError(wert) from fehler
    if ergebnis < 0:
        raise ValueError(wert)
    return ergebnis


def _datum(text: str) -> date | None:
    text = text.strip()[:10]
    for muster in ("%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, muster).date()
        except ValueError:
            continue
    return None


def _trenner(text: str) -> str:
    erste = text.splitlines()[0] if text.splitlines() else ""
    return max([";", ",", "\t"], key=erste.count)


def zeiterfassung(name: str, daten: bytes) -> Quelle:
    text = text_dekodieren(daten)
    leser = csv.DictReader(io.StringIO(text), delimiter=_trenner(text))
    summen: dict[tuple[str, str], Decimal] = {}
    tage: list[date] = []
    fehlerhafte = 0
    for zeile in leser:
        roh = _spalte(zeile, "stunden") or _spalte(zeile, "dauer")
        if not roh:
            continue  # Zeile ohne Dauer (z. B. Zwischensumme oder Leerzeile)
        try:
            dauer = stunden_lesen(roh)
        except ValueError:
            fehlerhafte += 1
            continue
        kunde = _spalte(zeile, "kunde") or "(ohne Kunde)"
        projekt = _spalte(zeile, "projekt") or "(ohne Projekt)"
        summen[(kunde, projekt)] = summen.get((kunde, projekt), Decimal(0)) + dauer
        tag = _datum(_spalte(zeile, "datum"))
        if tag:
            tage.append(tag)
    hinweise = []
    if fehlerhafte:
        hinweise.append(f"{fehlerhafte} Zeile(n) in „{name}“ ohne lesbare Dauer wurden nicht gezählt.")
    if not summen:
        return Quelle(
            "zeiterfassung", name, "zeiterfassung", "", hinweise=[*hinweise, f"„{name}“ enthält keine Zeiten."]
        )
    stunden = [
        {"kunde": k, "projekt": p, "stunden": str(s.quantize(Decimal("0.01"), ROUND_HALF_UP))}
        for (k, p), s in sorted(summen.items())
    ]
    zeilen = [f"- Kunde {s['kunde']}, Projekt {s['projekt']}: {s['stunden']} Stunden" for s in stunden]
    zeitraum = f"\nErfasste Tage: {min(tage).isoformat()} bis {max(tage).isoformat()}" if tage else ""
    inhalt = (
        "Summen aus der Zeiterfassung (bereits addiert, bitte unverändert übernehmen):\n" + "\n".join(zeilen) + zeitraum
    )
    return Quelle("zeiterfassung", name, "zeiterfassung", inhalt, stunden=stunden, hinweise=hinweise)


# ------------------------------------------------------------------ Mail
_TAGS = re.compile(r"<[^>]+>")


def mail_zerlegen(daten: bytes) -> tuple[EmailMessage, str, list[tuple[str, bytes]]]:
    """Gibt die Nachricht, den Text (Kopf und Inhalt) und die Anhänge zurück."""
    nachricht = email.message_from_bytes(daten, policy=email.policy.default)
    assert isinstance(nachricht, EmailMessage)
    koerper = nachricht.get_body(preferencelist=("plain", "html"))
    inhalt = ""
    if koerper is not None:
        inhalt = str(koerper.get_content())
        if koerper.get_content_type() == "text/html":
            inhalt = _TAGS.sub(" ", inhalt)
    anhaenge: list[tuple[str, bytes]] = []
    for teil in nachricht.iter_attachments():
        nutzlast = teil.get_payload(decode=True)
        if isinstance(nutzlast, bytes):
            anhaenge.append((teil.get_filename() or "anhang", nutzlast))
    kopf = (
        f"Von: {nachricht.get('From', '')}\nAn: {nachricht.get('To', '')}\n"
        f"Datum: {nachricht.get('Date', '')}\nBetreff: {nachricht.get('Subject', '')}"
    )
    inhalt = re.sub(r"[ \t]+", " ", inhalt).strip()
    return nachricht, f"{kopf}\n\n{inhalt}", anhaenge


def mail(name: str, daten: bytes) -> Quelle:
    _, text, anhaenge = mail_zerlegen(daten)
    text, hinweise = _kappen(text)
    if anhaenge:
        text += "\nAnhänge: " + ", ".join(n for n, _ in anhaenge)
    return Quelle("mail", name, "mail", text, hinweise=hinweise)


def notiz(name: str, daten: bytes) -> Quelle:
    text, hinweise = _kappen(text_dekodieren(daten))
    return Quelle("notiz", name, "notiz", text, hinweise=hinweise)
