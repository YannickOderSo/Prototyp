"""Typisierter Request für Views hinter Login und FirmaMiddleware."""

from django.http import HttpRequest

from .models import Firma, Mitgliedschaft, Nutzer


class FirmaRequest(HttpRequest):
    user: Nutzer
    firma: Firma
    mitgliedschaft: Mitgliedschaft
    darf_freigeben: bool
