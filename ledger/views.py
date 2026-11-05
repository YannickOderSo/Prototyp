from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import QuerySet
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.mandant import hole_oder_404
from accounts.rechte import firma_erforderlich, freigabe_berechtigt
from accounts.typen import FirmaRequest
from audit.services import protokolliere

from . import auswertung
from .forms import PostenFilterForm
from .models import Beleg, Kontakt, Kundentyp
from .services import kontakte_ohne_kundentyp, offene_belege, posten_filtern, zahlungen

SEITENGROESSE = 100


@firma_erforderlich
def posten(request: FirmaRequest) -> HttpResponse:
    heute = timezone.localdate()
    form = PostenFilterForm(request.GET or None)
    filter = form.cleaned_data if form.is_valid() else {}
    qs = posten_filtern(request.firma, filter, heute)
    seite = Paginator(qs, SEITENGROESSE).get_page(request.GET.get("seite"))
    summe = auswertung.kennzahlen(
        [auswertung.Posten(o, f, d) for o, f, d in qs.values_list("offen", "faellig_am", "belegdatum")],
        heute,
    )
    kontext = {"form": form, "seite": seite, "heute": heute, "summe": summe}
    vorlage = "ledger/_posten_liste.html" if request.headers.get("HX-Request") else "ledger/posten.html"
    return render(request, vorlage, kontext)


@firma_erforderlich
def kunden(request: FirmaRequest) -> HttpResponse:
    kontakte = Kontakt.objects.fuer(request.firma).filter(archiviert=False).order_by("name")
    return render(request, "ledger/kunden.html", {"kontakte": kontakte})


@firma_erforderlich
def kunde(request: FirmaRequest, pk: int) -> HttpResponse:
    kontakt = hole_oder_404(Kontakt, request.firma, pk=pk)
    heute = timezone.localdate()
    offene = offene_belege(request.firma).filter(kontakt=kontakt).order_by("faellig_am")
    bezahlt = (
        Beleg.objects.fuer(request.firma)
        .filter(kontakt=kontakt, status=Beleg.Status.BEZAHLT, bezahlt_am__isnull=False)
        .order_by("-bezahlt_am")[:24]
    )
    liste = zahlungen(request.firma, kontakt)
    return render(
        request,
        "ledger/kunde.html",
        {
            "kontakt": kontakt,
            "offene": offene,
            "bezahlt": bezahlt,
            "heute": heute,
            "summe_offen": sum((b.offen for b in offene), auswertung.NULL),
            "zahlungsdauer": auswertung.zahlungsdauer(liste, heute),
            "verzug": auswertung.verzug(liste, heute),
            "anzahl_zahlungen": len(auswertung.relevante_zahlungen(liste, heute)),
        },
    )


@firma_erforderlich
def kundentyp(request: FirmaRequest) -> HttpResponse:
    """Liste „Kundentyp fehlt“: Ohne Kundentyp wird nicht gemahnt (D3)."""
    kontakte: QuerySet[Kontakt]
    if request.GET.get("alle"):
        kontakte = (
            Kontakt.objects.fuer(request.firma).filter(kundentyp=Kundentyp.UNBEKANNT, archiviert=False).order_by("name")
        )
    else:
        kontakte = kontakte_ohne_kundentyp(request.firma)
    return render(request, "ledger/kundentyp.html", {"kontakte": kontakte, "alle": bool(request.GET.get("alle"))})


@require_POST
@freigabe_berechtigt
def kundentyp_setzen(request: FirmaRequest, pk: int) -> HttpResponse:
    kontakt = hole_oder_404(Kontakt, request.firma, pk=pk)
    neu = request.POST.get("kundentyp", "")
    if neu not in (Kundentyp.PRIVAT, Kundentyp.UNTERNEHMER, Kundentyp.UNBEKANNT):
        return HttpResponseBadRequest("Ungültiger Kundentyp")
    alt = kontakt.kundentyp
    if alt != neu:
        kontakt.kundentyp = neu
        kontakt.save(update_fields=["kundentyp"])
        protokolliere(
            request.firma,
            "kontakt.kundentyp_gesetzt",
            nutzer=request.user,
            objekt=kontakt,
            daten={"alt": alt, "neu": neu},
        )
    if request.headers.get("HX-Request"):
        return render(request, "ledger/_kundentyp_zeile.html", {"k": kontakt, "gespeichert": True})
    messages.success(request, f"Kundentyp für {kontakt.name} gespeichert.")
    return redirect(request.POST.get("zurueck") or "ledger:kundentyp")
