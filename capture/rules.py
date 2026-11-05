"""Regel-Engine der Erfassung (E4, E5, E10): Aus dem KI-Ergebnis wird ein prüfbarer Entwurf.

Grundsatz: Die KI ordnet zu, Regeln rechnen. Preis und Steuersatz einer Position stammen
- aus dem Lexware-Artikel (Spiegel), oder
- vom Nutzer in der Prüfansicht (nur wenn kein Artikel passt; nie aus einer Modellausgabe).
Ohne beides bleibt der Preis leer und der Entwurf ist blockiert.

„Blocker“ verhindern die Freigabe, „Hinweise“ muss der Nutzer lesen. Eigenbau; `belegfluss/regeln.py`
wurde nur als Orientierung gelesen (ADR-007).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CENT = Decimal("0.01")
ERLAUBTE_STEUERSAETZE = (Decimal("19"), Decimal("7"), Decimal("0"))
STUNDEN_EINHEITEN = {"stunde", "stunden", "std", "std.", "h"}
HERKUNFT_TEXT = {
    "gesprochen": "gehört",
    "foto": "aus Foto",
    "mail": "aus Mail",
    "zeiterfassung": "aus Zeiterfassung",
    "notiz": "aus Notiz",
    "nutzer": "vom Nutzer ergänzt",
}

# Anweisungen in Quellen, die wie ein Versuch aussehen, die Verarbeitung zu steuern (E9)
INJEKTIONSMUSTER = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"(setze|setz|stelle|ändere|aendere|mache?)\s+(den|die|alle)?\s*(preis|preise|betrag|summe|rabatt)",
        r"preis\w*\s+(auf|=)\s*0",
        r"ignorier\w*\s+(alle|die|vorherige\w*|bisherige\w*)?\s*(anweisung|regel|vorgabe)",
        r"ignore\s+(all\s+|the\s+)?(previous|prior|above)\s+(instructions|rules)",
        r"(system\s*prompt|du bist jetzt|you are now)",
        r"(rabatt|nachlass)\s+von\s+100",
        r"kostenlos\s+(abrechnen|berechnen|stellen)",
    )
]


@dataclass(frozen=True)
class KontaktInfo:
    extern_id: str
    name: str
    kundennummer: str = ""


@dataclass(frozen=True)
class ArtikelInfo:
    extern_id: str
    bezeichnung: str
    einheit: str
    netto: Decimal
    steuersatz: Decimal
    typ: str = "SERVICE"


@dataclass(frozen=True)
class AngebotInfo:
    nummer: str
    kontakt_extern_id: str | None
    positionen: tuple[tuple[str, Decimal], ...] = ()  # (artikel_id, menge)


@dataclass
class Position:
    beschreibung: str
    menge: Decimal
    einheit: str
    herkunft: str
    quelle: str
    artikel_id: str = ""
    artikel_bezeichnung: str = ""
    artikel_typ: str = ""
    netto: Decimal | None = None
    steuersatz: Decimal | None = None
    preis_herkunft: str = ""
    hinweis: str = ""

    @property
    def summe(self) -> Decimal | None:
        if self.netto is None:
            return None
        return (self.menge * self.netto).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Entwurf:
    belegart: str
    kunde_extern_id: str
    kunde_name: str
    angebot_nummer: str
    leistung_von: date | None
    leistung_bis: date | None
    steuerart: str
    positionen: list[Position] = field(default_factory=list)
    blocker: list[str] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)

    @property
    def freigabefaehig(self) -> bool:
        return not self.blocker

    def summen(self) -> dict[str, Any]:
        netto_je_satz: dict[Decimal, Decimal] = {}
        for p in self.positionen:
            if p.summe is not None and p.steuersatz is not None:
                netto_je_satz[p.steuersatz] = netto_je_satz.get(p.steuersatz, Decimal(0)) + p.summe
        steuer = {
            s: (n * s / 100).quantize(CENT, rounding=ROUND_HALF_UP) if self.steuerart != "vatfree" else Decimal("0.00")
            for s, n in netto_je_satz.items()
        }
        netto = sum(netto_je_satz.values(), Decimal("0.00"))
        return {"netto": netto, "steuer_je_satz": steuer, "brutto": netto + sum(steuer.values(), Decimal("0.00"))}


# ------------------------------------------------------------------ Hilfen
def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w&]+", " ", text.lower()).split())


def _namensvarianten(name: str) -> set[str]:
    varianten = {_norm(name)}
    if "," in name:  # „Musterfrau, Erika“ ↔ „Erika Musterfrau“
        nach, vor = name.split(",", 1)
        varianten.add(_norm(f"{vor} {nach}"))
    return varianten


def finde_kunde(name: str, kontakte: Iterable[KontaktInfo]) -> KontaktInfo | None:
    gesucht = _namensvarianten(name) if name.strip() else set()
    nummer = name.strip()
    for kontakt in kontakte:
        if gesucht & _namensvarianten(kontakt.name) or (kontakt.kundennummer and kontakt.kundennummer == nummer):
            return kontakt
    return None


def _decimal(wert: Any) -> Decimal | None:
    try:
        ergebnis = Decimal(str(wert))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return ergebnis if ergebnis.is_finite() else None


def _datum(text: Any) -> date | None:
    try:
        return date.fromisoformat(str(text)) if text else None
    except ValueError:
        return None


def injektionen(texte: Iterable[str]) -> list[str]:
    funde = []
    for text in texte:
        for muster in INJEKTIONSMUSTER:
            treffer = muster.search(text or "")
            if treffer:
                ausschnitt = text[max(0, treffer.start() - 20) : treffer.end() + 20].strip().replace("\n", " ")
                funde.append(f"Anweisung in einer Quelle erkannt und ignoriert: „…{ausschnitt}…“")
                break
    return funde


# ------------------------------------------------------------------ Positionen
def _position(roh: Mapping[str, Any], artikel: Mapping[str, ArtikelInfo], entwurf: Entwurf) -> Position | None:
    beschreibung = str(roh.get("beschreibung") or "").strip()[:255] or "(ohne Beschreibung)"
    menge = _decimal(roh.get("menge"))
    herkunft = str(roh.get("herkunft") or "notiz")
    position = Position(
        beschreibung=beschreibung,
        menge=menge if menge is not None else Decimal(0),
        einheit=str(roh.get("einheit") or "").strip()[:50],
        herkunft=herkunft if herkunft in HERKUNFT_TEXT else "notiz",
        quelle=str(roh.get("quelle") or "")[:100],
    )
    if menge is None or menge <= 0:
        entwurf.blocker.append(f"„{beschreibung}“: Menge fehlt oder ist nicht größer als 0.")
    artikel_id = str(roh.get("artikel_id") or "").strip()
    gefunden = artikel.get(artikel_id) if artikel_id else None
    if artikel_id and gefunden is None:
        entwurf.hinweise.append(f"„{beschreibung}“: Der genannte Artikel existiert nicht in Lexware.")
    if gefunden is not None:
        position.artikel_id = gefunden.extern_id
        position.artikel_bezeichnung = gefunden.bezeichnung
        position.artikel_typ = gefunden.typ
        position.netto = gefunden.netto
        position.steuersatz = gefunden.steuersatz
        position.preis_herkunft = f"aus Stammdaten (Lexware-Artikel „{gefunden.bezeichnung}“)"
        if gefunden.einheit and position.einheit and _norm(gefunden.einheit) != _norm(position.einheit):
            position.hinweis = f"Einheit laut Quelle „{position.einheit}“, laut Artikel „{gefunden.einheit}“."
            entwurf.hinweise.append(f"„{beschreibung}“: {position.hinweis}")
        position.einheit = gefunden.einheit or position.einheit
        return position
    # Kein Artikel: Preis nur, wenn der Nutzer ihn in der Prüfansicht gesetzt hat (nie aus der KI)
    preis = _decimal(roh.get("preis_nutzer"))
    satz = _decimal(roh.get("steuersatz_nutzer"))
    if preis is not None and preis >= 0 and satz in ERLAUBTE_STEUERSAETZE:
        position.netto = preis.quantize(CENT, rounding=ROUND_HALF_UP)
        position.steuersatz = satz
        position.preis_herkunft = "vom Nutzer gesetzt"
    else:
        entwurf.blocker.append(
            f"„{beschreibung}“: Kein passender Lexware-Artikel. Bitte Artikel wählen oder Preis und Steuersatz setzen."
        )
    return position


def _angebot_abgleichen(entwurf: Entwurf, angebot: AngebotInfo | None) -> None:
    """E10: Menge über Angebot als Mehraufwand markieren."""
    if not entwurf.angebot_nummer:
        return
    if angebot is None:
        entwurf.hinweise.append(f"Angebot {entwurf.angebot_nummer} wurde nicht gefunden. Kein Abgleich möglich.")
        return
    if angebot.kontakt_extern_id and entwurf.kunde_extern_id and angebot.kontakt_extern_id != entwurf.kunde_extern_id:
        entwurf.blocker.append(f"Angebot {angebot.nummer} gehört zu einem anderen Kunden.")
        return
    im_angebot: dict[str, Decimal] = {}
    for artikel_id, menge in angebot.positionen:
        im_angebot[artikel_id] = im_angebot.get(artikel_id, Decimal(0)) + menge
    abgerechnet: dict[str, Decimal] = {}
    for p in entwurf.positionen:
        if p.artikel_id:
            abgerechnet[p.artikel_id] = abgerechnet.get(p.artikel_id, Decimal(0)) + p.menge
    for artikel_id, menge in abgerechnet.items():
        if artikel_id in im_angebot and menge > im_angebot[artikel_id]:
            mehr = menge - im_angebot[artikel_id]
            bezeichnung = next(p.artikel_bezeichnung for p in entwurf.positionen if p.artikel_id == artikel_id)
            laut_angebot = im_angebot[artikel_id].normalize()
            text = (
                f"Mehraufwand: {mehr.normalize():f} mehr „{bezeichnung}“ als im Angebot {angebot.nummer} "
                f"({laut_angebot:f})."
            )
            entwurf.hinweise.append(text + " Ist das mit dem Kunden abgesprochen?")
            for p in entwurf.positionen:
                if p.artikel_id == artikel_id and not p.hinweis:
                    p.hinweis = "über Angebot"


def _zeiterfassung_abgleichen(
    entwurf: Entwurf, stunden: Sequence[Mapping[str, str]], kunde: KontaktInfo | None
) -> None:
    if not stunden or kunde is None:
        return
    namen = _namensvarianten(kunde.name)
    erfasst = sum(
        (_decimal(s.get("stunden")) or Decimal(0) for s in stunden if _norm(str(s.get("kunde", ""))) in namen),
        Decimal(0),
    )
    if erfasst <= 0:
        return
    abgerechnet = sum((p.menge for p in entwurf.positionen if p.einheit.lower() in STUNDEN_EINHEITEN), Decimal(0))
    if abs(abgerechnet - erfasst) > CENT:
        entwurf.hinweise.append(
            f"Zeiterfassung: {erfasst.quantize(CENT)} Stunden erfasst, "
            f"{abgerechnet.normalize():f} Stunden im Entwurf. Bitte abgleichen."
        )


# ------------------------------------------------------------------ Einstieg
def entwurf_bilden(
    ki: Mapping[str, Any],
    kontakte: Sequence[KontaktInfo],
    artikel: Mapping[str, ArtikelInfo],
    *,
    quelltexte: Iterable[str] = (),
    stunden: Sequence[Mapping[str, str]] = (),
    angebot: AngebotInfo | None = None,
    steuerart: str = "net",
    heute: date | None = None,
) -> Entwurf:
    kunde = finde_kunde(str(ki.get("kunde") or ""), kontakte)
    entwurf = Entwurf(
        belegart=str(ki.get("belegart") or "unklar"),
        kunde_extern_id=kunde.extern_id if kunde else "",
        kunde_name=kunde.name if kunde else str(ki.get("kunde") or "").strip(),
        angebot_nummer=str(ki.get("angebot_nummer") or "").strip(),
        leistung_von=_datum(ki.get("leistung_von")),
        leistung_bis=_datum(ki.get("leistung_bis")),
        steuerart=steuerart,
    )
    if entwurf.belegart not in ("angebot", "rechnung"):
        entwurf.blocker.append("Bitte wählen Sie, ob ein Angebot oder eine Rechnung entstehen soll.")
    if kunde is None:
        name = entwurf.kunde_name or "(ohne Namen)"
        entwurf.blocker.append(
            f"Kunde „{name}“ ist nicht in Lexware angelegt. Bitte Kunden wählen oder zuerst in Lexware anlegen."
        )
    for roh in ki.get("positionen") or []:
        position = _position(roh, artikel, entwurf)
        if position is not None:
            entwurf.positionen.append(position)
    if not entwurf.positionen:
        entwurf.blocker.append("Der Entwurf enthält keine Positionen.")
    if entwurf.belegart == "rechnung":
        if entwurf.leistung_von is None and entwurf.leistung_bis is None:
            entwurf.blocker.append("Leistungsdatum oder -zeitraum fehlt (Pflichtangabe auf Rechnungen).")
        elif entwurf.leistung_von and entwurf.leistung_bis and entwurf.leistung_von > entwurf.leistung_bis:
            entwurf.blocker.append("Der Leistungszeitraum endet vor seinem Beginn.")
        elif heute and (entwurf.leistung_bis or entwurf.leistung_von or heute) > heute:
            entwurf.hinweise.append("Der Leistungszeitraum liegt in der Zukunft.")
    _angebot_abgleichen(entwurf, angebot)
    _zeiterfassung_abgleichen(entwurf, stunden, kunde)
    entwurf.hinweise.extend(injektionen(quelltexte))
    entwurf.hinweise.extend(f"Offene Frage: {f}" for f in ki.get("offene_fragen") or [] if str(f).strip())
    return entwurf


# ------------------------------------------------------------------ Speichern als JSON
def als_json(entwurf: Entwurf) -> dict[str, Any]:
    daten = asdict(entwurf)
    for p, roh in zip(entwurf.positionen, daten["positionen"], strict=True):
        roh["summe"] = p.summe
    summen = entwurf.summen()
    daten["summen"] = {
        "netto": str(summen["netto"]),
        "brutto": str(summen["brutto"]),
        "steuer_je_satz": {str(k): str(v) for k, v in summen["steuer_je_satz"].items()},
    }
    return _strings(daten)


def _strings(wert: Any) -> Any:
    if isinstance(wert, Decimal):
        return str(wert)
    if isinstance(wert, date):
        return wert.isoformat()
    if isinstance(wert, dict):
        return {k: _strings(v) for k, v in wert.items()}
    if isinstance(wert, list):
        return [_strings(v) for v in wert]
    return wert
