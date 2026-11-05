"""Mandantentrennung (A4).

Fachliche Modelle erben von `FirmaModel`. Views holen Objekte ausschließlich über
`Model.objects.fuer(request.firma)` bzw. `hole_oder_404()`. Der generische IDOR-Test
(`tests/test_mandantentrennung.py`) prüft jede URL mit ID gegen Objekte einer fremden Firma.
"""

from typing import Any, TypeVar

from django.db import models
from django.http import Http404

from .models import Firma

M = TypeVar("M", bound="FirmaModel")


class FirmaQuerySet(models.QuerySet[M]):
    def fuer(self, firma: Firma | None) -> "FirmaQuerySet[M]":
        if firma is None:
            return self.none()
        return self.filter(firma=firma)


class FirmaManager(models.Manager[M]):
    def get_queryset(self) -> FirmaQuerySet[M]:
        return FirmaQuerySet(self.model, using=self._db)

    def fuer(self, firma: Firma | None) -> FirmaQuerySet[M]:
        return self.get_queryset().fuer(firma)


class FirmaModel(models.Model):
    firma = models.ForeignKey(Firma, on_delete=models.CASCADE, related_name="+")

    objects: FirmaManager[Any] = FirmaManager()

    class Meta:
        abstract = True


def hole_oder_404(modell: type[M], firma: Firma | None, **filter: Any) -> M:
    """Holt genau ein Objekt der Firma; fremde oder fehlende Objekte ergeben 404 (nie 403, kein Existenz-Leck)."""
    try:
        return modell.objects.fuer(firma).get(**filter)
    except (modell.DoesNotExist, ValueError, TypeError) as fehler:
        raise Http404 from fehler
