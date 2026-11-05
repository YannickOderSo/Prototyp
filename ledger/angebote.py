"""Angebote im Spiegel auswerten (M7-03/04, I2, I3): Zustand je Angebot und Kennzahlen je Zeitraum.

„Verschickt“ zählt Angebote mit Angebotsdatum im Zeitraum, ohne Entwürfe und stornierte (Lexware kennt über die API
keinen Versandzeitpunkt, siehe Offene-Fragen.md). Abgelaufen ist ein offenes Angebot nach seinem Ablaufdatum.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import QuerySet

from accounts.models import Firma

from .models import Beleg

BALD_TAGE = 7
GEZAEHLT = (Beleg.Status.OFFEN, Beleg.Status.ANGENOMMEN, Beleg.Status.ABGELEHNT)


def angebote(firma: Firma | None) -> QuerySet[Beleg]:
    return Beleg.objects.fuer(firma).filter(art=Beleg.Art.ANGEBOT, status__in=GEZAEHLT).select_related("kontakt")


def zustand(beleg: Beleg, heute: date) -> str:
    if beleg.status == Beleg.Status.ANGENOMMEN:
        return "angenommen"
    if beleg.status == Beleg.Status.ABGELEHNT:
        return "abgelehnt"
    if beleg.gueltig_bis and beleg.gueltig_bis < heute:
        return "abgelaufen"
    if beleg.gueltig_bis and (beleg.gueltig_bis - heute).days <= BALD_TAGE:
        return "laeuft_ab"
    return "offen"


@dataclass
class OffenesAngebot:
    beleg: Beleg
    zustand: str
    tage: int | None  # Tage bis Ablauf (negativ: seit Ablauf)


def offene(firma: Firma | None, heute: date, abgelaufene: bool = False) -> list[OffenesAngebot]:
    """Offene Angebote nach Ablaufdatum, zuerst die, die bald ablaufen; ohne Datum am Ende."""
    ergebnis = []
    for b in angebote(firma).filter(status=Beleg.Status.OFFEN):
        z = zustand(b, heute)
        if z == "abgelaufen" and not abgelaufene:
            continue
        ergebnis.append(OffenesAngebot(b, z, (b.gueltig_bis - heute).days if b.gueltig_bis else None))
    return sorted(
        ergebnis, key=lambda a: (a.zustand == "abgelaufen", a.tage is None, a.tage if a.tage is not None else 0)
    )


@dataclass
class Kennzahlen:
    verschickt: int = 0
    volumen: Decimal = Decimal("0.00")
    angenommen: int = 0
    angenommen_volumen: Decimal = Decimal("0.00")
    abgelehnt: int = 0
    abgelaufen: int = 0
    offen: int = 0
    offen_volumen: Decimal = Decimal("0.00")

    @property
    def entschieden(self) -> int:
        return self.angenommen + self.abgelehnt + self.abgelaufen

    @property
    def quote(self) -> int | None:
        """Annahmequote in Prozent über die entschiedenen Angebote (angenommen, abgelehnt, abgelaufen)."""
        if not self.entschieden:
            return None
        return round(100 * self.angenommen / self.entschieden)


def kennzahlen(firma: Firma | None, von: date, bis: date, heute: date) -> Kennzahlen:
    k = Kennzahlen()
    for b in angebote(firma).filter(belegdatum__gte=von, belegdatum__lte=bis):
        k.verschickt += 1
        k.volumen += b.brutto
        z = zustand(b, heute)
        if z == "angenommen":
            k.angenommen += 1
            k.angenommen_volumen += b.brutto
        elif z == "abgelehnt":
            k.abgelehnt += 1
        elif z == "abgelaufen":
            k.abgelaufen += 1
        else:
            k.offen += 1
            k.offen_volumen += b.brutto
    return k


def bald_ablaufend(firma: Firma | None, heute: date) -> int:
    return sum(1 for a in offene(firma, heute) if a.zustand == "laeuft_ab")
