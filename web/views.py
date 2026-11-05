from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from accounts.rechte import firma_erforderlich, nur_inhaber
from accounts.typen import FirmaRequest
from audit.services import protokolliere

from .forms import FirmendatenForm
from .rechtstexte import rechtstext as finde_rechtstext


def start(request: FirmaRequest) -> HttpResponse:
    if request.firma is None:
        return render(request, "web/start.html")
    from django.utils import timezone

    from connectors.models import Verbindung
    from ledger.services import cockpit

    verbindung = Verbindung.objects.fuer(request.firma).exclude(status=Verbindung.Status.GETRENNT).first()
    return render(
        request, "web/start.html", {"c": cockpit(request.firma, timezone.localdate()), "verbindung": verbindung}
    )


@login_not_required
def rechtstext(request: HttpRequest, slug: str) -> HttpResponse:
    text = finde_rechtstext(slug)
    if text is None:
        raise Http404
    return render(request, "web/rechtstext.html", {"text": text, "vorlage": f"web/rechtstexte/{text.slug}.html"})


@firma_erforderlich
def einstellungen(request: FirmaRequest) -> HttpResponse:
    ist_inhaber = request.mitgliedschaft.ist_inhaber
    form = FirmendatenForm(request.POST or None, instance=request.firma) if ist_inhaber else None
    if form is not None and request.method == "POST" and form.is_valid():
        geaendert = list(form.changed_data)
        form.save()
        protokolliere(
            request.firma,
            "einstellung.geaendert",
            nutzer=request.user,
            objekt=request.firma,
            daten={"felder": geaendert},
        )
        messages.success(request, "Firmendaten gespeichert.")
        return redirect("web:einstellungen")
    return render(request, "web/einstellungen.html", {"form": form, "ist_inhaber": ist_inhaber})


@nur_inhaber
def einrichtung(request: FirmaRequest) -> HttpResponse:
    from django.utils import timezone

    from dunning.vorschlaege import berechnen

    from . import einrichtung as dienst

    firma = request.firma
    if request.method == "POST":
        aktion = request.POST.get("aktion", "")
        if aktion == "vorlage" and request.POST.get("vorlage") in dienst.VORLAGEN:
            dienst.mahnplan_vorlage(firma, request.user, request.POST["vorlage"])
            messages.success(
                request, "Mahnplan übernommen. Feinheiten können Sie jederzeit unter Einstellungen ändern."
            )
        elif aktion == "abschliessen":
            dienst.abschliessen(firma, request.user)
            messages.success(request, "Einrichtung abgeschlossen. Ab morgen 5 Uhr entstehen täglich Vorschläge.")
            return redirect("web:start")
        return redirect("web:einrichtung")
    schritte = dienst.schritte(firma)
    probelauf = berechnen(firma, timezone.localdate()) if schritte[0].erledigt else None
    return render(
        request,
        "web/einrichtung.html",
        {
            "schritte": schritte,
            "vorlagen": dienst.VORLAGEN,
            "probelauf": probelauf,
        },
    )
