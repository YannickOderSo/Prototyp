"""Oberfläche des Excel-Imports (M6-08): hochladen → Spalten zuordnen → Vorschau → Freigabe → Ergebnis.

Alle Schritte nur für Inhaber und Freigeber; die Sitzung hat immer den zweiten Faktor (Middleware).
"""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from accounts.mandant import hole_oder_404
from accounts.rechte import firma_erforderlich, freigabe_berechtigt
from accounts.typen import FirmaRequest
from connectors.services import aktive_verbindung, ohne_lexware
from ledger.models import Beleg

from . import services
from .felder import FELDER, fehlende_pflichtfelder, vorlage_csv, vorlage_xlsx
from .forms import ERKLAERUNG, ERKLAERUNG_OHNE_LEXWARE, UploadForm, ZahlungForm
from .lesen import LeseFehler
from .models import ImportVorgang

STATUS_REIHENFOLGE = {"fehler": 0, "dublette": 1, "bezahlt": 2, "neu": 3}
STATUS_TEXT = {"neu": "wird angelegt", "dublette": "Dublette", "fehler": "Fehler", "bezahlt": "bezahlt"}
STEUERSAETZE = [("", "aus der Datei"), ("19", "19 %"), ("7", "7 %"), ("0", "0 %")]
ARTIKELTYPEN = [("", "aus der Datei"), ("SERVICE", "Dienstleistung"), ("PRODUCT", "Material / Ware")]


@freigabe_berechtigt
def uebersicht(request: FirmaRequest) -> HttpResponse:
    form = UploadForm(request.POST or None, request.FILES or None, initial={"art": request.GET.get("art", "kunden")})
    ohne = ohne_lexware(request.firma)
    if request.method == "POST" and form.is_valid() and ohne and form.cleaned_data["art"] == ImportVorgang.Art.ARTIKEL:
        form.add_error("art", services.ARTIKEL_NUR_MIT_LEXWARE)
    if request.method == "POST" and form.is_valid():
        datei = form.cleaned_data["datei"]
        try:
            vorgang = services.hochladen(
                request.firma,
                request.user,
                form.cleaned_data["art"],
                datei.name or "datei",
                datei.read(),
                form.cleaned_data["blatt"],
            )
        except LeseFehler as fehler:
            form.add_error("datei", str(fehler))
        else:
            return redirect("datenimport:vorgang", pk=vorgang.pk)
    return render(
        request,
        "datenimport/uebersicht.html",
        {
            "form": form,
            "vorgaenge": ImportVorgang.objects.fuer(request.firma).order_by("-erstellt")[:20],
            "verbunden": aktive_verbindung(request.firma) is not None,
            "ohne_lexware": ohne,
            "arten": [
                (wert, titel, (ERKLAERUNG_OHNE_LEXWARE if ohne else ERKLAERUNG)[wert])
                for wert, titel in ImportVorgang.Art.choices
            ],
        },
    )


@require_GET
@firma_erforderlich
def vorlage(request: FirmaRequest, art: str, format: str) -> HttpResponse:
    if art not in FELDER or format not in ("csv", "xlsx"):
        raise Http404
    if format == "csv":
        antwort = HttpResponse(vorlage_csv(art), content_type="text/csv; charset=utf-8")
    else:
        antwort = HttpResponse(
            vorlage_xlsx(art), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    antwort["Content-Disposition"] = f'attachment; filename="Vorlage_{art}.{format}"'
    return antwort


def _spalten_mit_beispiel(vorgang: ImportVorgang) -> list[dict[str, Any]]:
    beispiel = vorgang.zeilen[0] if vorgang.zeilen else []
    return [
        {"index": i, "titel": titel or f"Spalte {i + 1}", "beispiel": beispiel[i] if i < len(beispiel) else ""}
        for i, titel in enumerate(vorgang.spalten)
    ]


def _zeilen_mit_ergebnis(vorgang: ImportVorgang) -> list[dict[str, Any]]:
    ergebnis = vorgang.ergebnis.get("zeilen", {})
    zeilen = []
    for z in vorgang.vorschau:
        eintrag = ergebnis.get(str(z["nr"]), {})
        zeilen.append(
            {
                **z,
                "status_text": STATUS_TEXT.get(z["status"], z["status"]),
                "angelegt": bool(eintrag.get("id")),
                "fehler_anlage": eintrag.get("fehler", ""),
            }
        )
    return sorted(zeilen, key=lambda z: (STATUS_REIHENFOLGE.get(z["status"], 9), z["nr"]))


@require_GET
@freigabe_berechtigt
def vorgang(request: FirmaRequest, pk: int) -> HttpResponse:
    v = hole_oder_404(ImportVorgang, request.firma, pk=pk)
    felder = [
        {"feld": f, "gewaehlt": v.zuordnung.get(f.schluessel), "name": f"feld_{f.schluessel}"} for f in FELDER[v.art]
    ]
    return render(
        request,
        "datenimport/vorgang.html",
        {
            "v": v,
            "felder": felder,
            "spalten": _spalten_mit_beispiel(v),
            "fehlend": fehlende_pflichtfelder(v.art, v.zuordnung) if v.status == ImportVorgang.Status.ZUORDNUNG else [],
            "zeilen": _zeilen_mit_ergebnis(v),
            "anzahl": {s: v.anzahl(s) for s in STATUS_TEXT},
            "blaetter": v.ergebnis.get("blaetter", []),
            "steuersaetze": STEUERSAETZE,
            "artikeltypen": ARTIKELTYPEN,
            "verbunden": aktive_verbindung(request.firma) is not None,
            "ohne_lexware": ohne_lexware(request.firma),
            "haengt": v.status == ImportVorgang.Status.FREIGEGEBEN
            and v.art != ImportVorgang.Art.POSTEN
            and not services.job_aktiv(v),
            "erklaerung": (ERKLAERUNG_OHNE_LEXWARE if ohne_lexware(request.firma) else ERKLAERUNG)[v.art],
        },
    )


@require_POST
@freigabe_berechtigt
def zuordnung(request: FirmaRequest, pk: int) -> HttpResponse:
    v = hole_oder_404(ImportVorgang, request.firma, pk=pk)
    werte: dict[str, int] = {}
    for f in FELDER[v.art]:
        roh = request.POST.get(f"feld_{f.schluessel}", "")
        if roh.isdigit():
            werte[f.schluessel] = int(roh)
    standard: dict[str, str] = {}
    if v.art == ImportVorgang.Art.ARTIKEL:
        einheit = request.POST.get("standard_einheit", "").strip()[:50]
        satz = request.POST.get("standard_steuersatz", "")
        typ = request.POST.get("standard_typ", "")
        standard = {
            k: w
            for k, w in (
                ("einheit", einheit),
                ("steuersatz", satz if satz in ("0", "7", "19") else ""),
                ("typ", typ if typ in ("SERVICE", "PRODUCT") else ""),
            )
            if w
        }
    doppelt = {i for i in werte.values() if list(werte.values()).count(i) > 1}
    if doppelt:
        messages.error(request, "Jede Spalte darf nur einem Feld zugeordnet werden.")
        return redirect("datenimport:vorgang", pk=v.pk)
    try:
        fehlend = services.zuordnung_speichern(
            v, werte, standard, kundentyp_uebernehmen=request.POST.get("kundentyp_uebernehmen") == "1"
        )
    except services.ImportNichtMoeglich as fehler:
        messages.error(request, str(fehler))
    else:
        if fehlend:
            messages.error(request, "Bitte noch zuordnen: " + ", ".join(fehlend) + ".")
    return redirect("datenimport:vorgang", pk=v.pk)


@require_POST
@freigabe_berechtigt
def freigeben(request: FirmaRequest, pk: int) -> HttpResponse:
    v = hole_oder_404(ImportVorgang, request.firma, pk=pk)
    try:
        services.freigeben(v, request.user)
    except services.ImportNichtMoeglich as fehler:
        messages.error(request, str(fehler))
    else:
        v.refresh_from_db()
        if v.art == ImportVorgang.Art.POSTEN:
            messages.success(request, f"{v.ergebnis.get('angelegt', 0)} offene Rechnungen sind jetzt in Belegfluss.")
        elif v.status == ImportVorgang.Status.FERTIG:  # ohne Lexware: sofort fertig
            messages.success(request, f"{v.ergebnis.get('angelegt', 0)} Kunden sind jetzt in Belegfluss.")
        else:
            messages.success(request, "Freigegeben. Die Einträge werden jetzt im Hintergrund in Lexware angelegt.")
    return redirect("datenimport:vorgang", pk=v.pk)


@require_POST
@freigabe_berechtigt
def fortsetzen(request: FirmaRequest, pk: int) -> HttpResponse:
    v = hole_oder_404(ImportVorgang, request.firma, pk=pk)
    try:
        services.fortsetzen(v, request.user)
    except services.ImportNichtMoeglich as fehler:
        messages.error(request, str(fehler))
    else:
        messages.success(
            request, "Der Import wird fortgesetzt. Schon angelegte Einträge werden nicht doppelt angelegt."
        )
    return redirect("datenimport:vorgang", pk=v.pk)


@require_POST
@freigabe_berechtigt
def verwerfen(request: FirmaRequest, pk: int) -> HttpResponse:
    v = hole_oder_404(ImportVorgang, request.firma, pk=pk)
    try:
        services.verwerfen(v, request.user)
    except services.ImportNichtMoeglich as fehler:
        messages.error(request, str(fehler))
        return redirect("datenimport:vorgang", pk=v.pk)
    messages.info(request, "Import verworfen. Es wurde nichts angelegt.")
    return redirect("datenimport:uebersicht")


@require_POST
@freigabe_berechtigt
def zahlung(request: FirmaRequest, pk: int) -> HttpResponse:
    beleg = hole_oder_404(Beleg, request.firma, pk=pk)
    form = ZahlungForm(request.POST)
    if not form.is_valid():
        for fehler in form.errors.values():
            messages.error(request, " ".join(str(f) for f in fehler))
        return redirect("ledger:beleg", pk=beleg.pk)
    try:
        services.zahlung_eintragen(beleg, request.user, form.cleaned_data["bezahlt_am"], form.cleaned_data["offen"])
    except services.ImportNichtMoeglich as fehler:
        messages.error(request, str(fehler))
    else:
        messages.success(request, "Zahlstatus gespeichert.")
    return redirect("ledger:beleg", pk=beleg.pk)
