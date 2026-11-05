from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.mandant import hole_oder_404
from accounts.rechte import freigabe_berechtigt, nur_inhaber
from accounts.typen import FirmaRequest
from audit.services import protokolliere

from . import freigabe as dienst
from .forms import MahnplanForm
from .mail import inhalt, zinsberechnung_text
from .models import Mahnvorschlag
from .services import basiszins_fehlt, basiszinsen, mahnplan_fuer
from .vorschlaege import klaerung_noetig


@nur_inhaber
def mahnplan(request: FirmaRequest) -> HttpResponse:
    plan = mahnplan_fuer(request.firma)
    form = MahnplanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        geaendert = {f: str(form.cleaned_data[f]) for f in form.changed_data if not f.startswith(("text_", "betreff_"))}
        texte = [f for f in form.changed_data if f.startswith(("text_", "betreff_"))]
        plan = form.save(commit=False)
        plan.geaendert = timezone.now()
        plan.save()
        protokolliere(
            request.firma,
            "mahnplan.geaendert",
            nutzer=request.user,
            objekt=plan,
            daten={"werte": geaendert, "texte": texte},
        )
        messages.success(request, "Mahnplan gespeichert.")
        return redirect("dunning:mahnplan")
    return render(request, "dunning/mahnplan.html", {"form": form, "basiszinsen": basiszinsen()})


@freigabe_berechtigt
def freigabe(request: FirmaRequest) -> HttpResponse:
    alle = (
        Mahnvorschlag.objects.fuer(request.firma)
        .select_related("beleg", "beleg__kontakt")
        .order_by("stufe", "beleg__faellig_am", "pk")
    )
    offen = [v for v in alle.filter(status=Mahnvorschlag.Status.VORGESCHLAGEN)]
    return render(
        request,
        "dunning/freigabe.html",
        {
            "stufen": [
                (stufe, label, [v for v in offen if v.stufe == stufe]) for stufe, label in Mahnvorschlag.Stufe.choices
            ],
            "anzahl_offen": len(offen),
            "in_arbeit": alle.filter(status=Mahnvorschlag.Status.FREIGEGEBEN),
            "fehler": alle.filter(status=Mahnvorschlag.Status.FEHLER),
            "post": alle.filter(status=Mahnvorschlag.Status.POST_BEREIT),
            "versendet": alle.filter(status=Mahnvorschlag.Status.VERSENDET).order_by("-versendet_am")[:20],
            "klaerung": klaerung_noetig(request.firma, timezone.localdate()),
            "basiszins_fehlt": basiszins_fehlt(timezone.localdate()),
        },
    )


@require_POST
@freigabe_berechtigt
def freigeben(request: FirmaRequest) -> HttpResponse:
    ids = [int(i) for i in request.POST.getlist("vorschlag") if i.isdigit()]
    if not ids:
        messages.warning(request, "Bitte markieren Sie mindestens einen Vorschlag.")
        return redirect("dunning:freigabe")
    ergebnis = dienst.freigeben(request.firma, request.user, ids)
    if ergebnis.freigegeben:
        messages.success(request, f"{len(ergebnis.freigegeben)} freigegeben. Der Versand läuft im Hintergrund.")
    for vorschlag, grund in ergebnis.abgelehnt:
        messages.error(
            request, f"{vorschlag.get_stufe_display()} zu {vorschlag.beleg.nummer} {grund} und wurde nicht freigegeben."
        )
    return redirect("dunning:freigabe")


@require_POST
@freigabe_berechtigt
def verwerfen(request: FirmaRequest, pk: int) -> HttpResponse:
    vorschlag = hole_oder_404(Mahnvorschlag, request.firma, pk=pk)
    grund = request.POST.get("grund", "").strip()
    if not grund:
        messages.error(request, "Bitte geben Sie einen Grund an.")
        return redirect("dunning:freigabe")
    try:
        dienst.verwerfen(vorschlag, request.user, grund)
    except ValueError as fehler:
        messages.error(request, str(fehler))
    else:
        messages.info(request, f"Vorschlag zu {vorschlag.beleg.nummer} verworfen.")
    return redirect("dunning:freigabe")


@require_GET
@freigabe_berechtigt
def vorschau(request: FirmaRequest, pk: int) -> HttpResponse:
    vorschlag = hole_oder_404(Mahnvorschlag, request.firma, pk=pk)
    vorlage = "dunning/_vorschau.html" if request.headers.get("HX-Request") else "dunning/vorschau.html"
    return render(
        request, vorlage, {"v": vorschlag, "mail": inhalt(vorschlag), "zinsen": zinsberechnung_text(vorschlag)}
    )


@require_POST
@freigabe_berechtigt
def neuversuch(request: FirmaRequest, pk: int) -> HttpResponse:
    vorschlag = hole_oder_404(Mahnvorschlag, request.firma, pk=pk)
    try:
        dienst.neuversuch(vorschlag, request.user)
    except ValueError as fehler:
        messages.error(request, str(fehler))
    else:
        messages.success(request, "Neuer Versuch geplant.")
    return redirect("dunning:freigabe")


@require_GET
@freigabe_berechtigt
def pdf(request: FirmaRequest, pk: int) -> HttpResponse:
    vorschlag = hole_oder_404(Mahnvorschlag, request.firma, pk=pk, pdf__isnull=False)
    antwort = HttpResponse(bytes(vorschlag.pdf or b""), content_type="application/pdf")
    antwort["Content-Disposition"] = f'attachment; filename="{vorschlag.pdf_name or "Mahnung.pdf"}"'
    return antwort


@require_POST
@freigabe_berechtigt
def post_versendet(request: FirmaRequest, pk: int) -> HttpResponse:
    vorschlag = hole_oder_404(Mahnvorschlag, request.firma, pk=pk)
    try:
        dienst.als_post_versendet(vorschlag, request.user)
    except ValueError as fehler:
        messages.error(request, str(fehler))
    else:
        messages.success(
            request, f"{vorschlag.get_stufe_display()} zu {vorschlag.beleg.nummer} als per Post versendet vermerkt."
        )
    return redirect("dunning:freigabe")
