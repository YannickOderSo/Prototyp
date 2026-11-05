"""Fachlogik der Mahnautomatik, die auf die Datenbank zugreift."""

from __future__ import annotations

from datetime import date

from accounts.models import Firma

from .models import Basiszins, Mahnplan
from .recht import BasiszinsEintrag, basiszins_am


def mahnplan_fuer(firma: Firma) -> Mahnplan:
    plan, _ = Mahnplan.objects.get_or_create(firma=firma)
    return plan


def basiszinsen() -> list[Basiszins]:
    return list(Basiszins.objects.order_by("gueltig_ab"))


def basiszinstabelle() -> list[BasiszinsEintrag]:
    return [BasiszinsEintrag(b.gueltig_ab, b.satz) for b in basiszinsen()]


def basiszins_fehlt(heute: date) -> bool:
    """True, wenn für heute kein gültiger Basiszins gepflegt ist (Warnung im Cockpit)."""
    return basiszins_am(heute, basiszinstabelle()) is None
