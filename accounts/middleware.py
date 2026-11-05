"""Setzt `request.firma` und `request.mitgliedschaft` aus der Sitzung und den Mitgliedschaften.

Jede View holt fachliche Objekte nur über `request.firma` (Mandantentrennung, A4).
"""

from collections.abc import Callable

from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse

from .anmeldung import FIRMA, ZWEITER_FAKTOR_OK
from .models import Mitgliedschaft


class FirmaMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.firma = None  # type: ignore[attr-defined]
        request.mitgliedschaft = None  # type: ignore[attr-defined]
        request.darf_freigeben = False  # type: ignore[attr-defined]
        if request.user.is_authenticated:
            if not request.session.get(ZWEITER_FAKTOR_OK):
                # Verteidigung in der Tiefe: eine Sitzung ohne zweiten Faktor gilt nicht als angemeldet
                logout(request)
                return self.get_response(request)
            mitgliedschaften = Mitgliedschaft.objects.select_related("firma").filter(
                nutzer=request.user, firma__aktiv=True
            )
            gewaehlt = request.session.get(FIRMA)
            mitgliedschaft = next((m for m in mitgliedschaften if m.firma_id == gewaehlt), None)
            if mitgliedschaft is None:
                mitgliedschaft = next(iter(mitgliedschaften), None)
                if mitgliedschaft is not None:
                    request.session[FIRMA] = mitgliedschaft.firma_id
            if mitgliedschaft is not None:
                request.firma = mitgliedschaft.firma  # type: ignore[attr-defined]
                request.mitgliedschaft = mitgliedschaft  # type: ignore[attr-defined]
                request.darf_freigeben = mitgliedschaft.darf_freigeben  # type: ignore[attr-defined]
        return self.get_response(request)
