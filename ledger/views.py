from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.mandant import hole_oder_404
from accounts.rechte import firma_erforderlich
from accounts.typen import FirmaRequest

from . import auswertung
from .forms import PostenFilterForm
from .models import Beleg, Kontakt
from .services import offene_belege, posten_filtern, zahlungen

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
