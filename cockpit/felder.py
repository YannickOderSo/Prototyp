"""Gemeinsame Modellfelder. Geld immer als Decimal(12,2), Zinssätze als Decimal(6,4)."""

from typing import Any

from django.db import models


def geldfeld(verbose_name: str | None = None, **kwargs: Any) -> "models.DecimalField[Any, Any]":
    return models.DecimalField(verbose_name, max_digits=12, decimal_places=2, **kwargs)


def zinsfeld(verbose_name: str | None = None, **kwargs: Any) -> "models.DecimalField[Any, Any]":
    return models.DecimalField(verbose_name, max_digits=6, decimal_places=4, **kwargs)
