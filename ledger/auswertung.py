"""Kennzahlen des Forderungs-Cockpits (C1, C3, C4, C6) als reine Funktionen über einfachen Datensätzen.

Definitionen (siehe auch vault/02-Architektur/Datenmodell.md, Abschnitt Auswertung):
- offen: Status offen/überfällig und offener Betrag > 0.
- überfällig: Fälligkeit liegt vor heute. Ohne Fälligkeit gilt das Belegdatum als Fälligkeit.
- Altersstruktur: Tage überfällig in den Klassen 1–30, 31–60, 61–90, über 90; nicht fällige Posten separat.
- Zahlungsdauer: Tage vom Belegdatum bis zur Zahlung; Verzug: Tage von Fälligkeit bis Zahlung (bezahlte
  Rechnungen der letzten 12 Monate).
- Prognose: erwarteter Eingang = Fälligkeit + durchschnittlicher Verzug des Kunden (nie früher als die
  Fälligkeit). Liegt der erwartete Termin vor heute, ist der Eingang unsicher und zählt nicht in die Wochen.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

NULL = Decimal("0.00")
KLASSEN = (("1–30 Tage", 1, 30), ("31–60 Tage", 31, 60), ("61–90 Tage", 61, 90), ("über 90 Tage", 91, None))


@dataclass(frozen=True)
class Posten:
    """Minimale Sicht auf einen offenen Beleg für die Auswertung."""

    offen: Decimal
    faellig_am: date | None
    belegdatum: date | None = None
    kontakt_id: int | None = None

    def bezugsdatum(self) -> date | None:
        return self.faellig_am or self.belegdatum

    def tage_ueberfaellig(self, heute: date) -> int:
        bezug = self.bezugsdatum()
        return (heute - bezug).days if bezug else 0


@dataclass(frozen=True)
class Zahlung:
    belegdatum: date | None
    faellig_am: date | None
    bezahlt_am: date


@dataclass
class Klasse:
    name: str
    summe: Decimal = NULL
    anzahl: int = 0
    anteil: int = 0  # Prozent der überfälligen Summe, für die Balken


@dataclass
class Kennzahlen:
    summe_offen: Decimal = NULL
    anzahl_offen: int = 0
    summe_ueberfaellig: Decimal = NULL
    anzahl_ueberfaellig: int = 0
    summe_nicht_faellig: Decimal = NULL
    klassen: list[Klasse] = field(default_factory=list)

    @property
    def anzahl_nicht_faellig(self) -> int:
        return self.anzahl_offen - self.anzahl_ueberfaellig


def kennzahlen(posten: Iterable[Posten], heute: date) -> Kennzahlen:
    k = Kennzahlen(klassen=[Klasse(name) for name, _, _ in KLASSEN])
    for p in posten:
        if p.offen <= 0:
            continue
        k.summe_offen += p.offen
        k.anzahl_offen += 1
        tage = p.tage_ueberfaellig(heute)
        if tage <= 0:
            k.summe_nicht_faellig += p.offen
            continue
        k.summe_ueberfaellig += p.offen
        k.anzahl_ueberfaellig += 1
        for klasse, (_, von, bis) in zip(k.klassen, KLASSEN, strict=True):
            if tage >= von and (bis is None or tage <= bis):
                klasse.summe += p.offen
                klasse.anzahl += 1
                break
    if k.summe_ueberfaellig > 0:
        for klasse in k.klassen:
            klasse.anteil = int((klasse.summe * 100 / k.summe_ueberfaellig).quantize(Decimal("1"), ROUND_HALF_UP))
    return k


def _mittel(werte: Sequence[int]) -> Decimal | None:
    if not werte:
        return None
    return (Decimal(sum(werte)) / len(werte)).quantize(Decimal("0.1"), ROUND_HALF_UP)


def relevante_zahlungen(zahlungen: Iterable[Zahlung], heute: date, tage: int = 365) -> list[Zahlung]:
    grenze = heute - timedelta(days=tage)
    return [z for z in zahlungen if grenze <= z.bezahlt_am <= heute]


def zahlungsdauer(zahlungen: Iterable[Zahlung], heute: date) -> Decimal | None:
    """Durchschnittliche Tage von Belegdatum bis Zahlung, bezahlte Rechnungen der letzten 12 Monate (C3)."""
    return _mittel([(z.bezahlt_am - z.belegdatum).days for z in relevante_zahlungen(zahlungen, heute) if z.belegdatum])


def verzug(zahlungen: Iterable[Zahlung], heute: date) -> Decimal | None:
    """Durchschnittliche Tage von Fälligkeit bis Zahlung (negativ = vor Fälligkeit bezahlt)."""
    return _mittel([(z.bezahlt_am - z.faellig_am).days for z in relevante_zahlungen(zahlungen, heute) if z.faellig_am])


@dataclass
class Woche:
    beginn: date
    ende: date
    summe: Decimal = NULL
    anzahl: int = 0


@dataclass
class Prognose:
    wochen: list[Woche]
    unsicher: Decimal = NULL
    anzahl_unsicher: int = 0

    @property
    def summe(self) -> Decimal:
        return sum((w.summe for w in self.wochen), NULL)


def erwarteter_eingang(p: Posten, verzug_tage: Decimal | None) -> date | None:
    bezug = p.bezugsdatum()
    if bezug is None:
        return None
    tage = int(max(verzug_tage or Decimal(0), Decimal(0)).quantize(Decimal("1"), ROUND_HALF_UP))
    return bezug + timedelta(days=tage)


def prognose(
    posten: Iterable[Posten], verzug_je_kontakt: dict[int, Decimal | None], heute: date, wochen: int = 4
) -> Prognose:
    """Geldeingang der nächsten `wochen` Wochen (C4). Woche 1 beginnt heute."""
    ergebnis = Prognose(
        [Woche(heute + timedelta(days=7 * i), heute + timedelta(days=7 * i + 6)) for i in range(wochen)]
    )
    for p in posten:
        if p.offen <= 0:
            continue
        datum = erwarteter_eingang(p, verzug_je_kontakt.get(p.kontakt_id) if p.kontakt_id else None)
        if datum is None or datum < heute:
            ergebnis.unsicher += p.offen
            ergebnis.anzahl_unsicher += 1
            continue
        index = (datum - heute).days // 7
        if index < wochen:
            ergebnis.wochen[index].summe += p.offen
            ergebnis.wochen[index].anzahl += 1
    return ergebnis


@dataclass
class Monatswert:
    monat: date
    tage: Decimal | None
    anzahl: int
    anteil: int = 0


def verzug_je_monat(zahlungen: Iterable[Zahlung], heute: date, monate: int = 6) -> list[Monatswert]:
    """C6: durchschnittliche Tage von Fälligkeit bis Zahlung je Zahlungsmonat, die letzten `monate` Monate."""
    erster = heute.replace(day=1)
    starts = []
    for _ in range(monate):
        starts.append(erster)
        erster = (erster - timedelta(days=1)).replace(day=1)
    starts.reverse()
    werte: dict[date, list[int]] = {s: [] for s in starts}
    for z in zahlungen:
        if z.faellig_am is None:
            continue
        monat = z.bezahlt_am.replace(day=1)
        if monat in werte:
            werte[monat].append((z.bezahlt_am - z.faellig_am).days)
    ergebnis = [Monatswert(m, _mittel(v), len(v)) for m, v in werte.items()]
    hoechster = max((abs(w.tage) for w in ergebnis if w.tage is not None), default=Decimal(0))
    for w in ergebnis:
        if w.tage is not None and hoechster > 0:
            w.anteil = int((abs(w.tage) * 100 / hoechster).quantize(Decimal("1"), ROUND_HALF_UP))
    return ergebnis
