"""Hilfsfunktion zum Protokollieren. Daten enthalten nur IDs und Sachwerte, keine Freitexte von Kunden."""

from typing import TYPE_CHECKING, Any

from django.db import models

from .models import Protokolleintrag

if TYPE_CHECKING:
    from accounts.models import Firma, Nutzer


def protokolliere(
    firma: "Firma",
    ereignis: str,
    *,
    nutzer: "Nutzer | None" = None,
    objekt: models.Model | None = None,
    daten: dict[str, Any] | None = None,
) -> Protokolleintrag:
    """Schreibt einen Protokolleintrag. `nutzer` ist None bei Aktionen des Systems (z. B. Worker)."""
    if nutzer is not None and not getattr(nutzer, "is_authenticated", False):
        nutzer = None
    return Protokolleintrag.objects.create(
        firma=firma,
        nutzer=nutzer,
        ereignis=ereignis,
        objekt_typ=objekt._meta.label if objekt is not None else "",
        objekt_id=str(objekt.pk) if objekt is not None else "",
        daten=daten or {},
    )
