from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.rechte import nur_inhaber
from accounts.typen import FirmaRequest

from .fehler import ConnectorFehler
from .forms import SchluesselForm
from .models import Verbindung
from .services import trennen, verbinden


@nur_inhaber
def lexware(request: FirmaRequest) -> HttpResponse:
    verbindung = Verbindung.objects.fuer(request.firma).filter(typ=Verbindung.Typ.LEXWARE).first()
    form = SchluesselForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            verbindung = verbinden(request.firma, request.user, form.cleaned_data["schluessel"])
        except ConnectorFehler as fehler:
            form.add_error("schluessel", _meldung(fehler))
        else:
            from ledger.aufgaben import erstimport_einplanen

            erstimport_einplanen(verbindung)
            messages.success(request, f"Verbunden mit Lexware: {verbindung.firmenname_extern}. Der Erstimport läuft.")
            return redirect("connectors:lexware")
    return render(request, "connectors/lexware.html", {"form": form, "verbindung": verbindung})


def _meldung(fehler: ConnectorFehler) -> str:
    """Deutsche Meldung für die Oberfläche; technische Details nur, wenn sie verständlich sind."""
    text = str(fehler)
    return text if text and not text.startswith("HTTP") else fehler.meldung


@require_POST
@nur_inhaber
def lexware_trennen(request: FirmaRequest) -> HttpResponse:
    verbindung = Verbindung.objects.fuer(request.firma).filter(typ=Verbindung.Typ.LEXWARE).first()
    if verbindung is not None and verbindung.status != Verbindung.Status.GETRENNT:
        trennen(verbindung, request.user)
        messages.info(request, "Die Verbindung zu Lexware ist getrennt. Der Schlüssel wurde gelöscht.")
    return redirect("connectors:lexware")
