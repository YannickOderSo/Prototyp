"""Verzug, Verzugszinsen und Pauschale als reine Funktionen (§§ 286, 288 BGB).

Keine Rechtsberatung; umgesetzt exakt nach vault/02-Architektur/Mahnlogik-und-Recht.md. Wo die Regeln
Spielraum lassen, gilt die für den Schuldner günstigere Auslegung (eingetragen in Offene-Fragen.md):

- Verzugsbeginn ist der Tag, den die Tabelle nennt. Zinsen laufen ab dem FOLGETAG bis einschließlich
  Stichtag (§ 187 Abs. 1 BGB entsprechend). Am Tag des Verzugsbeginns selbst entstehen keine Zinsen und
  keine Pauschale.
- § 286 Abs. 3: Die 30 Tage laufen ab dem späteren Datum aus Fälligkeit und Zugang der Rechnung
  (Zugang = Belegdatum + 3 Tage).
- Teilzahlungen: Zinsen auf den aktuell offenen Betrag für den ganzen Zeitraum (nie mehr als geschuldet).
- Ein Basiszins gilt höchstens bis zum nächsten 1.1. bzw. 1.7.; fehlt der Folgewert, werden keine
  Zinsen berechnet und der Inhaber gewarnt.
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
NULL = Decimal("0.00")
PAUSCHALE = Decimal("40.00")
MINDESTZINSEN = Decimal("1.00")
AUFSCHLAG = {"privat": Decimal("5"), "unternehmer": Decimal("9")}
FRIST_286_ABS_3_TAGE = 30
ZUGANG_RECHNUNG_TAGE = 3
ZUGANG_MAHNUNG_TAGE = 1

PRIVAT = "privat"
UNTERNEHMER = "unternehmer"


@dataclass(frozen=True)
class BasiszinsEintrag:
    gueltig_ab: date
    satz: Decimal


@dataclass(frozen=True)
class Forderung:
    belegdatum: date | None
    faellig_am: date | None
    kundentyp: str
    verzugshinweis: bool = False  # Rechnung enthielt den Hinweis nach § 286 Abs. 3 S. 1 Hs. 2


def zugang_rechnung(belegdatum: date) -> date:
    return belegdatum + timedelta(days=ZUGANG_RECHNUNG_TAGE)


def zugang_mahnung(versanddatum: date) -> date:
    return versanddatum + timedelta(days=ZUGANG_MAHNUNG_TAGE)


def verzugsbeginn(forderung: Forderung, erinnerung_versendet_am: date | None = None) -> date | None:
    """Tag des Verzugsbeginns oder None (kein Verzug berechenbar bzw. noch nicht eingetreten).

    `erinnerung_versendet_am`: Versanddatum der ersten Mahnung nach Fälligkeit (Stufe 0).
    """
    faellig = forderung.faellig_am
    if faellig is None or forderung.kundentyp not in (PRIVAT, UNTERNEHMER):
        return None
    erste_mahnung = erinnerung_versendet_am if erinnerung_versendet_am and erinnerung_versendet_am > faellig else None

    if forderung.kundentyp == UNTERNEHMER or forderung.verzugshinweis:
        bezug = max(faellig, zugang_rechnung(forderung.belegdatum)) if forderung.belegdatum else faellig
        beginn = bezug + timedelta(days=FRIST_286_ABS_3_TAGE)
        if forderung.kundentyp == UNTERNEHMER and erste_mahnung is not None:
            # Tabelle: früheres Datum aus „Zugang Stufe 0 + 1 Tag“ und „Fälligkeit + 30“
            durch_mahnung = zugang_mahnung(erste_mahnung) + timedelta(days=1)
            beginn = min(beginn, durch_mahnung)
        return beginn

    # Privatkunde ohne Hinweis: Verzug erst durch Zugang der ersten Mahnung nach Fälligkeit (§ 286 Abs. 1)
    return zugang_mahnung(erste_mahnung) if erste_mahnung is not None else None


def verzug_besteht(beginn: date | None, stichtag: date) -> bool:
    return beginn is not None and stichtag > beginn


def naechster_wechsel(tag: date) -> date:
    """Nächster möglicher Basiszins-Wechsel (1.1. oder 1.7.) strikt nach `tag`."""
    return date(tag.year, 7, 1) if tag < date(tag.year, 7, 1) else date(tag.year + 1, 1, 1)


def basiszins_am(tag: date, tabelle: Sequence[BasiszinsEintrag]) -> Decimal | None:
    eintrag = None
    for e in sorted(tabelle, key=lambda e: e.gueltig_ab):
        if e.gueltig_ab <= tag:
            eintrag = e
    if eintrag is None or tag >= naechster_wechsel(eintrag.gueltig_ab):
        return None
    return eintrag.satz


@dataclass(frozen=True)
class ZinsAbschnitt:
    von: date
    bis: date
    tage: int
    basiszins: Decimal
    zinssatz: Decimal
    jahrestage: int
    betrag: Decimal


@dataclass(frozen=True)
class ZinsErgebnis:
    betrag: Decimal = NULL
    abschnitte: tuple[ZinsAbschnitt, ...] = ()
    basiszins_fehlt: bool = False
    unter_mindestbetrag: bool = False
    grundlage: Decimal = NULL
    aufschlag: Decimal = NULL


def verzugszinsen(
    offen: Decimal,
    beginn: date | None,
    stichtag: date,
    kundentyp: str,
    tabelle: Sequence[BasiszinsEintrag],
) -> ZinsErgebnis:
    """Taggenaue Verzugszinsen auf den offenen Betrag (§ 288 Abs. 1 und 2 BGB), abschnittsweise je Basiszins
    und Kalenderjahr (Divisor 365, im Schaltjahr 366). Jeder Abschnitt wird auf Cent gerundet (ROUND_HALF_UP)."""
    if beginn is None or stichtag <= beginn or offen <= 0 or kundentyp not in AUFSCHLAG:
        return ZinsErgebnis(grundlage=offen)
    aufschlag = AUFSCHLAG[kundentyp]
    abschnitte: list[ZinsAbschnitt] = []
    tag = beginn + timedelta(days=1)
    while tag <= stichtag:
        basis = basiszins_am(tag, tabelle)
        if basis is None:
            return ZinsErgebnis(basiszins_fehlt=True, grundlage=offen, aufschlag=aufschlag)
        ende = min(stichtag, naechster_wechsel(tag) - timedelta(days=1))
        tage = (ende - tag).days + 1
        jahrestage = 366 if calendar.isleap(tag.year) else 365
        zinssatz = basis + aufschlag
        betrag = (offen * zinssatz / 100 * tage / jahrestage).quantize(CENT, rounding=ROUND_HALF_UP)
        abschnitte.append(ZinsAbschnitt(tag, ende, tage, basis, zinssatz, jahrestage, betrag))
        tag = ende + timedelta(days=1)
    summe = sum((a.betrag for a in abschnitte), NULL)
    if summe < MINDESTZINSEN:
        return ZinsErgebnis(NULL, tuple(abschnitte), unter_mindestbetrag=True, grundlage=offen, aufschlag=aufschlag)
    return ZinsErgebnis(summe, tuple(abschnitte), grundlage=offen, aufschlag=aufschlag)


def pauschale(kundentyp: str, beginn: date | None, stichtag: date, bereits_geltend_gemacht: bool = False) -> Decimal:
    """40 € nur bei Unternehmern, nur bei Verzug, einmal je Forderung (§ 288 Abs. 5 BGB). Nie bei Privatkunden."""
    if kundentyp != UNTERNEHMER or bereits_geltend_gemacht or not verzug_besteht(beginn, stichtag):
        return NULL
    return PAUSCHALE


def _euro(betrag: Decimal) -> str:
    text = f"{betrag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"


def _prozent(wert: Decimal) -> str:
    return f"{wert.normalize():f}".replace(".", ",")


def zinstext(ergebnis: ZinsErgebnis) -> str:
    """Berechnungsgrundlage für Mahnung und Mail, eine Zeile je Abschnitt."""
    if not ergebnis.abschnitte or ergebnis.betrag <= 0:
        return ""
    zeilen = [
        f"{_euro(ergebnis.grundlage)} × {_prozent(a.zinssatz)} % p. a. (Basiszins {_prozent(a.basiszins)} % "
        f"+ {_prozent(ergebnis.aufschlag)} Prozentpunkte) × {a.tage}/{a.jahrestage} Tage "
        f"({a.von:%d.%m.%Y}–{a.bis:%d.%m.%Y}) = {_euro(a.betrag)}"
        for a in ergebnis.abschnitte
    ]
    return "\n".join(zeilen)


@dataclass
class MahnBetraege:
    offen: Decimal
    zinsen: Decimal = NULL
    pauschale: Decimal = NULL
    verzugsbeginn: date | None = None
    zinsergebnis: ZinsErgebnis = field(default_factory=ZinsErgebnis)
    hinweise: list[str] = field(default_factory=list)

    @property
    def gesamt(self) -> Decimal:
        return self.offen + self.zinsen + self.pauschale


def berechne(
    stufe: int,
    forderung: Forderung,
    offen: Decimal,
    stichtag: date,
    tabelle: Sequence[BasiszinsEintrag],
    erinnerung_versendet_am: date | None = None,
    zinsen_aktiv: bool = True,
    pauschale_aktiv: bool = True,
    pauschale_bereits_geltend_gemacht: bool = False,
) -> MahnBetraege:
    """Beträge einer Erinnerung (Stufe 0: nie Zinsen oder Pauschale) bzw. Mahnung (Stufe 1 und 2)."""
    beginn = verzugsbeginn(forderung, erinnerung_versendet_am)
    ergebnis = MahnBetraege(offen=offen, verzugsbeginn=beginn)
    if forderung.faellig_am is None:
        ergebnis.hinweise.append("Fälligkeit fehlt in Lexware: keine Zinsen und keine Pauschale berechenbar.")
    if stufe == 0:
        return ergebnis
    if forderung.faellig_am is not None and not verzug_besteht(beginn, stichtag):
        ergebnis.hinweise.append("Verzug ist noch nicht eingetreten: keine Zinsen und keine Pauschale.")
    if zinsen_aktiv:
        zins = verzugszinsen(offen, beginn, stichtag, forderung.kundentyp, tabelle)
        ergebnis.zinsergebnis = zins
        ergebnis.zinsen = zins.betrag
        if zins.basiszins_fehlt:
            ergebnis.hinweise.append(
                "Für einen Teil des Zeitraums ist kein aktueller Basiszins gepflegt: keine Zinsen berechnet."
            )
    if pauschale_aktiv:
        ergebnis.pauschale = pauschale(forderung.kundentyp, beginn, stichtag, pauschale_bereits_geltend_gemacht)
        if pauschale_bereits_geltend_gemacht and forderung.kundentyp == UNTERNEHMER:
            ergebnis.hinweise.append("Die Pauschale wurde bereits mit einer früheren Mahnung geltend gemacht.")
    return ergebnis
