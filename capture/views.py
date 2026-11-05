from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.mandant import hole_oder_404
from accounts.rechte import firma_erforderlich
from accounts.typen import FirmaRequest

from .dateien import MAX_AUFNAHME_SEKUNDEN, DateiAbgelehnt
from .models import Erfassung
from .services import anlegen


@firma_erforderlich
def liste(request: FirmaRequest) -> HttpResponse:
    erfassungen = Erfassung.objects.fuer(request.firma).order_by("-erstellt")[:50]
    return render(request, "capture/liste.html", {"erfassungen": erfassungen})


@firma_erforderlich
def neu(request: FirmaRequest) -> HttpResponse:
    return render(request, "capture/neu.html", {"max_sekunden": MAX_AUFNAHME_SEKUNDEN})


@require_POST
@firma_erforderlich
def hochladen(request: FirmaRequest) -> HttpResponse:
    dateien: list[tuple[str, bytes]] = [(f.name or "datei", f.read()) for f in request.FILES.getlist("dateien")]
    aufnahme = request.FILES.get("aufnahme")
    if aufnahme is not None and not isinstance(aufnahme, list):
        dateien.insert(0, (aufnahme.name or "aufnahme.webm", aufnahme.read()))
    kanal = Erfassung.Kanal.AUFNAHME if "aufnahme" in request.FILES else Erfassung.Kanal.UPLOAD
    ist_fetch = request.headers.get("X-Requested-With") == "fetch"
    try:
        erfassung = anlegen(request.firma, request.user, kanal, dateien, notiz=request.POST.get("notiz", ""))
    except DateiAbgelehnt as fehler:
        if ist_fetch:
            return JsonResponse({"fehler": str(fehler)}, status=400)
        messages.error(request, str(fehler))
        return redirect("capture:neu")
    ziel = reverse("capture:detail", args=[erfassung.pk])
    if ist_fetch:
        return JsonResponse({"weiter": ziel})
    return redirect(ziel)


@firma_erforderlich
def detail(request: FirmaRequest, pk: int) -> HttpResponse:
    erfassung = hole_oder_404(Erfassung, request.firma, pk=pk)
    return render(request, "capture/detail.html", {"e": erfassung})
