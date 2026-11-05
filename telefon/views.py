"""Oberfläche des Telefonassistenten (J5, J6) und Anmeldung eines Anrufs durch Asterisk (J7)."""

from __future__ import annotations

import hmac
import json
import uuid as uuidlib

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from accounts.mandant import hole_oder_404
from accounts.rechte import firma_erforderlich, nur_inhaber
from accounts.typen import FirmaRequest
from audit.services import protokolliere

from . import gespraech as fuehrung
from .forms import EinstellungForm, ErledigtForm
from .models import Gespraech, Rueckruf, Telefonassistent

REIHENFOLGE = {"dringend": 0, "normal": 1, "niedrig": 2}


@require_GET
@firma_erforderlich
def rueckrufe(request: FirmaRequest) -> HttpResponse:
    alle = Rueckruf.objects.fuer(request.firma).select_related("kontakt", "erledigt_von")
    offen = sorted(
        alle.filter(status=Rueckruf.Status.OFFEN),
        key=lambda r: (REIHENFOLGE.get(r.dringlichkeit, 9), -r.erstellt.timestamp()),
    )
    return render(
        request,
        "telefon/rueckrufe.html",
        {
            "offen": offen,
            "erledigt": alle.filter(status=Rueckruf.Status.ERLEDIGT).order_by("-erledigt_am")[:20],
            "einstellung": Telefonassistent.objects.fuer(request.firma).first(),
        },
    )


@require_GET
@firma_erforderlich
def rueckruf(request: FirmaRequest, pk: int) -> HttpResponse:
    r = hole_oder_404(Rueckruf, request.firma, pk=pk)
    return render(request, "telefon/rueckruf.html", {"r": r, "form": ErledigtForm(initial={"notiz": r.notiz})})


@require_POST
@firma_erforderlich
def erledigt(request: FirmaRequest, pk: int) -> HttpResponse:
    r = hole_oder_404(Rueckruf, request.firma, pk=pk)
    form = ErledigtForm(request.POST)
    if not form.is_valid():
        return redirect("telefon:rueckruf", pk=r.pk)
    if request.POST.get("aktion") == "wieder_oeffnen":
        r.status, r.erledigt_von, r.erledigt_am = Rueckruf.Status.OFFEN, None, None
        ereignis = "telefon.rueckruf_wieder_offen"
    else:
        r.status, r.erledigt_von, r.erledigt_am = Rueckruf.Status.ERLEDIGT, request.user, timezone.now()
        ereignis = "telefon.rueckruf_erledigt"
    r.notiz = form.cleaned_data["notiz"]
    r.save(update_fields=["status", "erledigt_von", "erledigt_am", "notiz"])
    protokolliere(request.firma, ereignis, nutzer=request.user, objekt=r)
    messages.success(request, "Rückruf erledigt." if r.status == Rueckruf.Status.ERLEDIGT else "Rückruf wieder offen.")
    return (
        redirect("telefon:rueckrufe") if r.status == Rueckruf.Status.ERLEDIGT else redirect("telefon:rueckruf", pk=r.pk)
    )


@nur_inhaber
def einstellungen(request: FirmaRequest) -> HttpResponse:
    einstellung = Telefonassistent.objects.fuer(request.firma).first() or Telefonassistent(firma=request.firma)
    form = EinstellungForm(request.POST or None, instance=einstellung)
    if request.method == "POST" and form.is_valid():
        geaendert = list(form.changed_data)
        e = form.save(commit=False)
        e.firma = request.firma
        e.geaendert = timezone.now()
        e.save()
        protokolliere(
            request.firma, "telefon.einstellungen_geaendert", nutzer=request.user, objekt=e, daten={"felder": geaendert}
        )
        messages.success(request, "Telefonassistent gespeichert.")
        return redirect("telefon:einstellungen")
    return render(
        request,
        "telefon/einstellungen.html",
        {"form": form, "einstellung": einstellung, "ansage": fuehrung.ansage(request.firma)},
    )


# ------------------------------------------------------------------ Testanruf im Browser (J6)


@require_GET
@firma_erforderlich
def testanruf(request: FirmaRequest) -> HttpResponse:
    return render(request, "telefon/testanruf.html")


def _test_gespraech(request: FirmaRequest, kennung: str) -> Gespraech:
    try:
        wert = uuidlib.UUID(str(kennung))
    except ValueError as fehler:
        raise Http404 from fehler
    return hole_oder_404(Gespraech, request.firma, uuid=wert, kanal=Gespraech.Kanal.TEST)


def _ergebnis(g: Gespraech, antwort: fuehrung.Antwort) -> JsonResponse:
    daten: dict[str, object] = {"antwort": antwort.text, "beendet": antwort.beendet, "ausfallbetrieb": g.ausfallbetrieb}
    rueckruf = Rueckruf.objects.filter(gespraech=g).first()
    if rueckruf is not None:
        from django.urls import reverse

        daten["rueckruf"] = reverse("telefon:rueckruf", args=[rueckruf.pk])
    return JsonResponse(daten)


@require_POST
@firma_erforderlich
def test_start(request: FirmaRequest) -> JsonResponse:
    nummer = str(request.POST.get("nummer", ""))[:40]
    g, text = fuehrung.starten(request.firma, Gespraech.Kanal.TEST, anrufer_nummer=nummer, nutzer=request.user)
    return JsonResponse({"gespraech": str(g.uuid), "antwort": text, "beendet": False})


@require_POST
@firma_erforderlich
def test_nachricht(request: FirmaRequest, kennung: str) -> JsonResponse:
    g = _test_gespraech(request, kennung)
    text = str(request.POST.get("text", ""))
    gehoert = ""
    if "audio" in request.FILES:
        from capture.transkription import TranskriptionFehler, transkribieren

        audio = request.FILES.get("audio")
        if audio is None or isinstance(audio, list):
            return JsonResponse({"fehler": "Keine Aufnahme erhalten."}, status=400)
        if audio.size and audio.size > 10 * 1024 * 1024:
            return JsonResponse({"fehler": "Die Aufnahme ist zu lang."}, status=400)
        try:
            text = gehoert = transkribieren(
                audio.read(), audio.name or "beitrag.webm", audio.content_type or "audio/webm"
            )
        except TranskriptionFehler as fehler:
            return JsonResponse({"fehler": str(fehler)}, status=503)
    if not text.strip():
        return JsonResponse({"fehler": "Es wurde nichts verstanden. Bitte noch einmal."}, status=400)
    antwort = fuehrung.antworten(g, text)
    antwort_json = _ergebnis(g, antwort)
    daten = json.loads(antwort_json.content)
    if gehoert:
        daten["gehoert"] = gehoert  # nur bei Sprache: Text zur Kontrolle anzeigen
    return JsonResponse(daten)


@require_POST
@firma_erforderlich
def test_ende(request: FirmaRequest, kennung: str) -> JsonResponse:
    g = _test_gespraech(request, kennung)
    fuehrung.auflegen(g)
    g.refresh_from_db()
    return _ergebnis(g, fuehrung.Antwort("", beendet=True))


# ------------------------------------------------------------------ Anmeldung durch Asterisk (J7)


@csrf_exempt
@login_not_required
@require_POST
def asterisk_anruf(request: HttpRequest) -> HttpResponse:
    """Asterisk meldet einen Anruf an (Dialplan: CURL mit did, clip, token) und bekommt die Gesprächs-UUID zurück.

    Geschützt durch ein Geheimnis aus der Umgebung (TELEFON_ASTERISK_TOKEN). Zuordnung der Firma über die
    angerufene Nummer; nur eingeschaltete Assistenten nehmen an.
    """
    erwartet = getattr(settings, "TELEFON_ASTERISK_TOKEN", "")
    gesendet = str(request.POST.get("token", "") or request.headers.get("X-Belegfluss-Token", ""))
    if not erwartet or not hmac.compare_digest(erwartet, gesendet):
        return HttpResponse("verboten", status=403, content_type="text/plain")
    angerufen = fuehrung._nummer(str(request.POST.get("did", "")))
    einstellung = (
        Telefonassistent.objects.select_related("firma")
        .filter(rufnummer=angerufen, aktiv=True, firma__aktiv=True)
        .first()
        if angerufen
        else None
    )
    if einstellung is None:
        return HttpResponse("unbekannt", status=404, content_type="text/plain")
    g, _ = fuehrung.starten(
        einstellung.firma,
        Gespraech.Kanal.TELEFON,
        anrufer_nummer=str(request.POST.get("clip", "")),
        angerufene_nummer=angerufen,
    )
    return HttpResponse(str(g.uuid), content_type="text/plain")
