"""Pausen „nicht mahnen bis …“ für Kunde und Beleg (D8)."""

from __future__ import annotations

from datetime import date

from django.db import transaction

from accounts.models import Nutzer
from audit.services import protokolliere

from .models import Beleg, Kontakt


def _offene_vorschlaege_zurueckziehen(belege: list[Beleg], nutzer: Nutzer) -> int:
    from dunning.models import Mahnvorschlag

    vorschlaege = Mahnvorschlag.objects.filter(beleg__in=belege, status=Mahnvorschlag.Status.VORGESCHLAGEN)
    anzahl = 0
    for vorschlag in vorschlaege.select_related("firma", "beleg"):
        protokolliere(
            vorschlag.firma,
            "mahnvorschlag.zurueckgezogen",
            nutzer=nutzer,
            objekt=vorschlag.beleg,
            daten={"stufe": vorschlag.stufe, "grund": "pausiert"},
        )
        vorschlag.delete()  # nie freigegeben, keine Außenwirkung
        anzahl += 1
    return anzahl


@transaction.atomic
def beleg_pausieren(beleg: Beleg, bis: date | None, nutzer: Nutzer, heute: date) -> int:
    beleg.mahnpause_bis = bis
    beleg.save(update_fields=["mahnpause_bis"])
    protokolliere(
        beleg.firma,
        "beleg.pause_gesetzt" if bis else "beleg.pause_aufgehoben",
        nutzer=nutzer,
        objekt=beleg,
        daten={"bis": bis.isoformat() if bis else None},
    )
    return _offene_vorschlaege_zurueckziehen([beleg], nutzer) if bis and bis >= heute else 0


@transaction.atomic
def kontakt_pausieren(kontakt: Kontakt, bis: date | None, notiz: str, nutzer: Nutzer, heute: date) -> int:
    kontakt.mahnpause_bis = bis
    kontakt.notiz = notiz
    kontakt.save(update_fields=["mahnpause_bis", "notiz"])
    protokolliere(
        kontakt.firma,
        "kontakt.pause_gesetzt" if bis else "kontakt.pause_aufgehoben",
        nutzer=nutzer,
        objekt=kontakt,
        daten={"bis": bis.isoformat() if bis else None},
    )
    if bis and bis >= heute:
        return _offene_vorschlaege_zurueckziehen(list(Beleg.objects.filter(kontakt=kontakt)), nutzer)
    return 0
