"""Rollenprüfung für Views (A3)."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

from .models import Rolle

View = Callable[..., HttpResponse]


def rolle_erforderlich(*rollen: Rolle) -> Callable[[View], View]:
    """Erlaubt die View nur Mitgliedern der aktiven Firma mit einer der Rollen."""

    def dekorator(view: View) -> View:
        @wraps(view)
        def pruefen(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            mitgliedschaft = getattr(request, "mitgliedschaft", None)
            if mitgliedschaft is None or mitgliedschaft.rolle not in rollen:
                raise PermissionDenied("Für diese Aktion fehlt Ihnen die Berechtigung.")
            return view(request, *args, **kwargs)

        return pruefen

    return dekorator


def firma_erforderlich(view: View) -> View:
    """Jede fachliche View braucht eine aktive Firma; alle Rollen dürfen lesen."""
    return rolle_erforderlich(Rolle.INHABER, Rolle.FREIGEBER, Rolle.MITARBEITER)(view)


nur_inhaber = rolle_erforderlich(Rolle.INHABER)
freigabe_berechtigt = rolle_erforderlich(Rolle.INHABER, Rolle.FREIGEBER)
