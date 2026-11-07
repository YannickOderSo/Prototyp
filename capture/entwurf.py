"""Regeln auf eine Erfassung anwenden: Eingaben aus dem Spiegel laden, Ergebnis speichern."""

from __future__ import annotations

import copy
from typing import Any

from django.utils import timezone

from connectors.fehler import ConnectorFehler
from connectors.services import aktive_verbindung, connector_fuer, ohne_lexware
from ledger.models import Artikel, Beleg, Kontakt

from . import rules
from .models import Erfassung


def _angebot(erfassung: Erfassung, nummer: str) -> rules.AngebotInfo | None:
    if not nummer:
        return None
    beleg = (
        Beleg.objects.fuer(erfassung.firma)
        .filter(art=Beleg.Art.ANGEBOT, nummer=nummer)
        .exclude(status=Beleg.Status.STORNIERT)
        .select_related("kontakt")
        .first()
    )
    if beleg is None:
        return None
    positionen: list[tuple[str, Any]] = []
    verbindung = aktive_verbindung(erfassung.firma)
    if verbindung is not None:
        try:
            positionen = connector_fuer(verbindung).get_quotation_positions(beleg.extern_id)
        except ConnectorFehler:
            positionen = []
    return rules.AngebotInfo(
        nummer=beleg.nummer,
        kontakt_extern_id=beleg.kontakt.extern_id if beleg.kontakt else None,
        positionen=tuple(positionen),
    )


def regeln_anwenden(erfassung: Erfassung, zusatz_hinweise: list[str] | None = None) -> rules.Entwurf:
    """Bildet aus `erfassung.eingabe` den Entwurf und speichert Entwurf, Blocker und Hinweise."""
    firma = erfassung.firma
    if not erfassung.eingabe:
        erfassung.eingabe = copy.deepcopy(erfassung.ki_ergebnis)
    kontakte = [
        rules.KontaktInfo(k.extern_id, k.name, k.kundennummer)
        for k in Kontakt.objects.fuer(firma).filter(archiviert=False)
    ]
    artikel = {
        a.extern_id: rules.ArtikelInfo(a.extern_id, a.bezeichnung, a.einheit, a.netto, a.steuersatz, a.typ)
        for a in Artikel.objects.fuer(firma).filter(archiviert=False)
    }
    verbindung = aktive_verbindung(firma)
    entwurf = rules.entwurf_bilden(
        erfassung.eingabe,
        kontakte,
        artikel,
        quelltexte=[erfassung.transkript, erfassung.notiz, *(str(q.get("text", "")) for q in erfassung.quellen)],
        stunden=[s for q in erfassung.quellen for s in q.get("stunden", [])],
        angebot=_angebot(erfassung, str(erfassung.eingabe.get("angebot_nummer") or "")),
        steuerart=verbindung.steuerart if verbindung else "net",
        heute=timezone.localdate(),
        ohne_lexware=ohne_lexware(firma),
    )
    erfassung.entwurf = rules.als_json(entwurf)
    erfassung.blocker = entwurf.blocker
    erfassung.hinweise = [*(zusatz_hinweise or []), *entwurf.hinweise]
    erfassung.save(update_fields=["eingabe", "entwurf", "blocker", "hinweise"])
    return entwurf
