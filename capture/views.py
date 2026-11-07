from datetime import date
from typing import Any

from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.mandant import hole_oder_404
from accounts.rechte import firma_erforderlich, freigabe_berechtigt, nur_inhaber
from accounts.typen import FirmaRequest

from .dateien import MAX_AUFNAHME_SEKUNDEN, DateiAbgelehnt
from .models import Erfassung
from .services import anlegen


@firma_erforderlich
def liste(request: FirmaRequest) -> HttpResponse:
    """„Angebote & Rechnungen“ (I1): neu erstellen, Entwürfe in Arbeit, offene Angebote, Weg zu den Rechnungen."""
    from django.utils import timezone

    from ledger import angebote
    from ledger.services import offene_belege

    heute = timezone.localdate()
    erfassungen = Erfassung.objects.fuer(request.firma).order_by("-erstellt")[:50]
    offen = offene_belege(request.firma)
    return render(
        request,
        "capture/liste.html",
        {
            "erfassungen": erfassungen,
            "offene_angebote": angebote.offene(request.firma, heute, abgelaufene=True)[:30],
            "offene_rechnungen": offen.count(),
            "ueberfaellige_rechnungen": offen.filter(faellig_am__lt=heute).count(),
        },
    )


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
    from connectors.services import ohne_lexware

    from .pruefung import ansicht

    erfassung = hole_oder_404(Erfassung, request.firma, pk=pk)
    kontext: dict[str, object] = {"e": erfassung, "ohne_lexware": ohne_lexware(request.firma)}
    if erfassung.status in (
        Erfassung.Status.PRUEFUNG,
        Erfassung.Status.FREIGEGEBEN,
        Erfassung.Status.UEBERTRAGEN,
        Erfassung.Status.AUSGEGEBEN,
    ):
        kontext.update(ansicht(erfassung))
    return render(request, "capture/detail.html", kontext)


@require_POST
@firma_erforderlich
def pruefen(request: FirmaRequest, pk: int) -> HttpResponse:
    from .pruefung import aenderungen_uebernehmen

    erfassung = hole_oder_404(Erfassung, request.firma, pk=pk)
    try:
        aenderungen_uebernehmen(erfassung, request.user, request.POST)
    except ValueError as fehler:
        messages.error(request, str(fehler))
    else:
        messages.success(request, "Änderungen übernommen und neu geprüft.")
    return redirect("capture:detail", pk=erfassung.pk)


@require_POST
@firma_erforderlich
def verwerfen(request: FirmaRequest, pk: int) -> HttpResponse:
    from audit.services import protokolliere

    erfassung = hole_oder_404(Erfassung, request.firma, pk=pk)
    if erfassung.status in (Erfassung.Status.UEBERTRAGEN, Erfassung.Status.FREIGEGEBEN):
        messages.error(request, "Bereits freigegebene Entwürfe können hier nicht verworfen werden.")
    else:
        erfassung.status = Erfassung.Status.VERWORFEN
        erfassung.save(update_fields=["status"])
        protokolliere(request.firma, "erfassung.verworfen", nutzer=request.user, objekt=erfassung)
        messages.info(request, "Entwurf verworfen.")
    return redirect("capture:liste")


@require_POST
@firma_erforderlich
def neuversuch(request: FirmaRequest, pk: int) -> HttpResponse:
    erfassung = hole_oder_404(Erfassung, request.firma, pk=pk)
    if erfassung.status == Erfassung.Status.FEHLER:
        from .services import aufbereitung_einplanen

        erfassung.status = Erfassung.Status.WARTET
        erfassung.fehler = ""
        erfassung.save(update_fields=["status", "fehler"])
        aufbereitung_einplanen(erfassung)
        messages.info(request, "Neuer Versuch gestartet.")
    return redirect("capture:detail", pk=erfassung.pk)


@require_POST
@firma_erforderlich
def transkript(request: FirmaRequest, pk: int) -> HttpResponse:
    from .services import transkript_speichern

    erfassung = hole_oder_404(Erfassung, request.firma, pk=pk)
    erzeugen = request.POST.get("aktion") == "erzeugen"
    try:
        transkript_speichern(erfassung, request.user, request.POST.get("transkript", ""), erzeugen)
    except ValueError as fehler:
        messages.error(request, str(fehler))
    else:
        messages.success(request, "Der Entwurf wird erzeugt." if erzeugen else "Text gespeichert.")
    return redirect("capture:detail", pk=erfassung.pk)


@require_POST
@freigabe_berechtigt
def freigeben(request: FirmaRequest, pk: int) -> HttpResponse:
    """Nur Inhaber und Freigeber (A3), nur per POST aus einer 2FA-Sitzung (ADR-004)."""
    from connectors.services import ohne_lexware

    from .uebertragung import freigeben as dienst
    from .uebertragung import positionsliste_ausgeben

    erfassung = hole_oder_404(Erfassung, request.firma, pk=pk)
    if ohne_lexware(request.firma):
        try:
            positionsliste_ausgeben(erfassung, request.user)
        except ValueError as fehler:
            messages.error(request, str(fehler))
            return redirect("capture:detail", pk=erfassung.pk)
        messages.success(request, "Freigegeben. Übertragen Sie die Positionen jetzt in Ihr Rechnungsprogramm.")
        return redirect("capture:positionsliste", pk=erfassung.pk)
    try:
        dienst(erfassung, request.user)
    except ValueError as fehler:
        messages.error(request, str(fehler))
    else:
        messages.success(request, "Freigegeben. Der Entwurf wird in Lexware angelegt.")
    return redirect("capture:detail", pk=erfassung.pk)


def _ausgegeben(request: FirmaRequest, pk: int) -> Erfassung:
    erfassung = hole_oder_404(Erfassung, request.firma, pk=pk)
    if erfassung.status != Erfassung.Status.AUSGEGEBEN:
        raise Http404
    return erfassung


@firma_erforderlich
def positionsliste(request: FirmaRequest, pk: int) -> HttpResponse:
    """ADR-011 Stufe 1: Positionsliste zum Abtippen, deutlich als Entwurf, ohne Nummer, keine Rechnung."""
    erfassung = _ausgegeben(request, pk)
    return render(request, "capture/positionsliste.html", {"e": erfassung, "liste": _liste(erfassung)})


@firma_erforderlich
def positionsliste_csv(request: FirmaRequest, pk: int) -> HttpResponse:
    from audit.services import protokolliere
    from reports.export import csv_text

    erfassung = _ausgegeben(request, pk)
    liste = _liste(erfassung)
    zeilen = [
        [p["nr"], p["beschreibung"], p["menge"], p["einheit"], p["netto"], p["steuersatz"], p["summe"]]
        for p in liste["positionen"]
    ]
    kopf = ["Pos.", "Beschreibung", "Menge", "Einheit", "Einzelpreis netto (EUR)", "USt (%)", "Summe netto (EUR)"]
    antwort = HttpResponse(csv_text(kopf, zeilen), content_type="text/csv; charset=utf-8")
    antwort["Content-Disposition"] = f'attachment; filename="Positionsliste-Entwurf_{erfassung.pk}.csv"'
    protokolliere(request.firma, "erfassung.positionsliste_csv", nutzer=request.user, objekt=erfassung)
    return antwort


def _deutsch(wert: object) -> str:
    """Zahl als deutsche Schreibweise für CSV und Anzeige (1234.5 → 1234,50; Mengen ohne unnötige Nullen)."""
    from decimal import Decimal, InvalidOperation

    if wert in (None, ""):
        return ""
    try:
        zahl = Decimal(str(wert))
    except InvalidOperation:
        return ""
    return f"{zahl:.2f}".replace(".", ",")


def _menge(wert: object) -> str:
    from decimal import Decimal, InvalidOperation

    try:
        zahl = Decimal(str(wert))
    except InvalidOperation:
        return str(wert or "")
    text = format(zahl.normalize(), "f")
    return text.replace(".", ",")


def _iso_datum(wert: object) -> date | None:
    try:
        return date.fromisoformat(str(wert)) if wert else None
    except ValueError:
        return None


def _liste(erfassung: Erfassung) -> dict[str, Any]:
    entwurf = erfassung.entwurf
    positionen = [
        {
            "nr": i,
            "beschreibung": p.get("beschreibung", ""),
            "menge": _menge(p.get("menge")),
            "einheit": p.get("einheit", ""),
            "netto": _deutsch(p.get("netto")),
            "steuersatz": _menge(p.get("steuersatz")) if p.get("steuersatz") not in (None, "") else "",
            "summe": _deutsch(p.get("summe")),
        }
        for i, p in enumerate(entwurf.get("positionen", []), start=1)
    ]
    return {
        "belegart": entwurf.get("belegart", ""),
        "kunde": entwurf.get("kunde_name", ""),
        "leistung_von": _iso_datum(entwurf.get("leistung_von")),
        "leistung_bis": _iso_datum(entwurf.get("leistung_bis")),
        "angebot_nummer": entwurf.get("angebot_nummer", ""),
        "positionen": positionen,
        "ohne_preis": sum(1 for p in positionen if not p["netto"]),
        "summe_netto": _deutsch((entwurf.get("summen") or {}).get("netto")),
    }


@nur_inhaber
def postfach(request: FirmaRequest) -> HttpResponse:
    from audit.services import protokolliere

    from .models import Belegpostfach
    from .postfach import adresse

    eintrag, _ = Belegpostfach.objects.get_or_create(firma=request.firma)
    if request.method == "POST":
        if request.POST.get("aktion") == "neue_adresse":
            from .models import _postfach_token

            eintrag.token = _postfach_token()
            messages.info(request, "Neue Belegadresse erzeugt. Die alte nimmt keine Mails mehr an.")
        else:
            zeilen = [z.strip().lower() for z in request.POST.get("absender", "").splitlines() if z.strip()]
            eintrag.absender = [z for z in zeilen if "@" in z][:200]
            eintrag.aktiv = bool(request.POST.get("aktiv"))
            messages.success(request, "Belegpostfach gespeichert.")
        eintrag.save()
        protokolliere(
            request.firma,
            "einstellung.belegpostfach",
            nutzer=request.user,
            objekt=eintrag,
            daten={"aktiv": eintrag.aktiv, "anzahl_absender": len(eintrag.absender)},
        )
        return redirect("capture:postfach")
    return render(request, "capture/postfach.html", {"postfach": eintrag, "adresse": adresse(eintrag)})
