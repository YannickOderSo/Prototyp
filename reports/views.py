from django.http import HttpResponse
from django.shortcuts import render

from accounts.rechte import freigabe_berechtigt
from accounts.typen import FirmaRequest

from .wochenbericht import bericht


@freigabe_berechtigt
def uebersicht(request: FirmaRequest) -> HttpResponse:
    return render(request, "reports/uebersicht.html", {"b": bericht(request.firma)})
