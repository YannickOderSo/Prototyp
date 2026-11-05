"""Protokoll aller Aktionen mit Außenwirkung (F2). Nur anhängen: kein Update, kein Delete.

Doppelt abgesichert: auf Modellebene (save/delete/QuerySet) und in Postgres per Trigger
(siehe Migration 0002). Einträge älter als 8 Jahre darf nur der Löschjob entfernen.
"""

from typing import Any, NoReturn

from django.conf import settings
from django.db import models
from django.utils import timezone


class ProtokollGeschuetzt(Exception):
    pass


class ProtokollQuerySet(models.QuerySet["Protokolleintrag"]):
    def update(self, **kwargs: Any) -> NoReturn:
        raise ProtokollGeschuetzt("Protokolleinträge sind unveränderlich")

    def delete(self) -> NoReturn:
        raise ProtokollGeschuetzt("Protokolleinträge dürfen nicht gelöscht werden")


class Protokolleintrag(models.Model):
    firma = models.ForeignKey("accounts.Firma", on_delete=models.PROTECT, related_name="protokoll")
    nutzer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    zeit = models.DateTimeField(default=timezone.now, db_index=True)
    ereignis = models.CharField(max_length=100)
    objekt_typ = models.CharField(max_length=100, blank=True)
    objekt_id = models.CharField(max_length=100, blank=True)
    daten = models.JSONField(default=dict, blank=True)

    objects = ProtokollQuerySet.as_manager()

    class Meta:
        ordering = ["-zeit", "-id"]
        indexes = [models.Index(fields=["firma", "-zeit"], name="protokoll_firma_zeit_idx")]
        verbose_name = "Protokolleintrag"
        verbose_name_plural = "Protokoll"

    def __str__(self) -> str:
        return f"{self.zeit:%Y-%m-%d %H:%M} {self.ereignis}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ProtokollGeschuetzt("Protokolleinträge sind unveränderlich")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise ProtokollGeschuetzt("Protokolleinträge dürfen nicht gelöscht werden")
