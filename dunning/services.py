"""Fachlogik der Mahnautomatik, die auf die Datenbank zugreift."""

from __future__ import annotations

from accounts.models import Firma

from .models import Basiszins, Mahnplan


def mahnplan_fuer(firma: Firma) -> Mahnplan:
    plan, _ = Mahnplan.objects.get_or_create(firma=firma)
    return plan


def basiszinsen() -> list[Basiszins]:
    return list(Basiszins.objects.order_by("gueltig_ab"))
