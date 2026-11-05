from django.http import HttpResponse
from django.shortcuts import render

from accounts.rechte import freigabe_berechtigt, nur_inhaber
from accounts.typen import FirmaRequest

from .wochenbericht import ZEITRAEUME, bericht


@freigabe_berechtigt
def uebersicht(request: FirmaRequest) -> HttpResponse:
    art = request.GET.get("zeitraum", "woche")
    return render(
        request,
        "reports/uebersicht.html",
        {"b": bericht(request.firma, art=art), "zeitraeume": list(ZEITRAEUME.items())},
    )


@nur_inhaber
def export(request: FirmaRequest) -> HttpResponse:
    from django.utils import timezone

    from audit.services import protokolliere

    from .export import zip_export

    inhalt = zip_export(request.firma)
    protokolliere(
        request.firma, "export.erstellt", nutzer=request.user, objekt=request.firma, daten={"bytes": len(inhalt)}
    )
    antwort = HttpResponse(inhalt, content_type="application/zip")
    antwort["Content-Disposition"] = f'attachment; filename="cockpit-export-{timezone.localdate():%Y-%m-%d}.zip"'
    return antwort
