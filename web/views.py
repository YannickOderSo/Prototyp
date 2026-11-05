from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from accounts.rechte import firma_erforderlich
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
