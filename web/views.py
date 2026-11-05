from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from accounts.models import Firma
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
    heute = timezone.localdate()
    reiter = [("ueberblick", "Überblick"), ("rechnungen", "Rechnungen"), ("angebote", "Angebote")]
    if request.darf_freigeben:
        reiter.append(("mahnungen", "Mahnungen"))
    ansicht = request.GET.get("ansicht", "ueberblick")
    if ansicht not in dict(reiter):
        ansicht = "ueberblick"
    kontext: dict[str, object] = {
        "c": cockpit(request.firma, heute),
        "verbindung": verbindung,
        "reiter": reiter,
        "ansicht": ansicht,
        "heute": heute,
    }
    kontext.update(reiter_daten(request.firma, ansicht, heute))
    return render(request, "web/start.html", kontext)


def reiter_daten(firma: Firma, ansicht: str, heute: date) -> dict[str, object]:
    """Kennzahlen und kurze Listen je Cockpit-Reiter (I2). Nur der gewählte Reiter wird berechnet."""
    from datetime import timedelta

    from django.db.models import Count, Sum

    from dunning.models import Mahnvorschlag
    from ledger import angebote
    from ledger.models import Beleg
    from ledger.services import offene_belege

    if ansicht == "rechnungen":
        monatsanfang = heute.replace(day=1)
        bezahlt = (
            Beleg.objects.fuer(firma)
            .filter(status=Beleg.Status.BEZAHLT, bezahlt_am__gte=monatsanfang, bezahlt_am__lte=heute)
            .exclude(art=Beleg.Art.ANGEBOT)
        )
        summe = bezahlt.aggregate(s=Sum("brutto"), n=Count("id"))
        offen = offene_belege(firma)
        return {
            "bezahlt_monat": summe["s"] or 0,
            "bezahlt_monat_anzahl": summe["n"],
            "naechste": list(offen.filter(faellig_am__gte=heute).order_by("faellig_am")[:5]),
            "ohne_faelligkeit": offen.filter(faellig_am__isnull=True).count(),
        }
    if ansicht == "angebote":
        from dunning.models import Angebotserinnerung

        return {
            "erinnerungen_offen": Angebotserinnerung.objects.fuer(firma)
            .filter(status=Angebotserinnerung.Status.VORGESCHLAGEN)
            .count(),
            "ak": angebote.kennzahlen(firma, heute - timedelta(days=90), heute, heute),
            "offene_angebote": angebote.offene(firma, heute)[:8],
            "bald": angebote.bald_ablaufend(firma, heute),
        }
    if ansicht == "mahnungen":
        vorschlaege = Mahnvorschlag.objects.fuer(firma)
        offen_in_mahnung = offene_belege(firma).filter(mahnstufe__gt=0).aggregate(s=Sum("offen"), n=Count("id"))
        return {
            "zur_freigabe": vorschlaege.filter(status=Mahnvorschlag.Status.VORGESCHLAGEN).count(),
            "im_versand": vorschlaege.filter(
                status__in=[Mahnvorschlag.Status.FREIGEGEBEN, Mahnvorschlag.Status.POST_BEREIT]
            ).count(),
            "versendet_monat": vorschlaege.filter(
                status=Mahnvorschlag.Status.VERSENDET, versendet_am__date__gte=heute.replace(day=1)
            ).count(),
            "in_mahnung": offen_in_mahnung["s"] or 0,
            "in_mahnung_anzahl": offen_in_mahnung["n"],
            "naechste_vorschlaege": list(
                vorschlaege.filter(status=Mahnvorschlag.Status.VORGESCHLAGEN)
                .select_related("beleg", "beleg__kontakt")
                .order_by("-stufe", "beleg__faellig_am")[:5]
            ),
        }
    return {}


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
