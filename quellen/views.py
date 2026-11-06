"""Seite „Abgleich“ (ADR-011 Stufe 3): Rechnungskopien und Kontoauszüge. Nur Inhaber und Freigeber."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.mandant import hole_oder_404
from accounts.rechte import freigabe_berechtigt
from accounts.typen import FirmaRequest
from audit.services import protokolliere

from . import bank, kopien, zahlungen
from .forms import KontoauszugForm, KopienUploadForm, PruefForm
from .models import Kontoauszug, Kopieadresse, Rechnungskopie, Zahlung


def kopie_adresse(eintrag: Kopieadresse | None) -> str:
    if eintrag is None:
        return ""
    lokal, _, domain = settings.BELEGPOSTFACH_ADRESSE.partition("@")
    return f"{lokal}+{eintrag.token}@{domain}" if domain else ""


def _zusammenfassung(liste: list[Rechnungskopie]) -> str:
    zaehler = {s: 0 for s in Rechnungskopie.Status.values}
    for k in liste:
        zaehler[k.status] += 1
    teile = []
    if zaehler["angelegt"]:
        teile.append(f"{zaehler['angelegt']} übernommen")
    if zaehler["pruefung"]:
        teile.append(f"{zaehler['pruefung']} zu prüfen")
    if zaehler["doppelt"]:
        teile.append(f"{zaehler['doppelt']} schon vorhanden")
    if zaehler["abgelehnt"]:
        teile.append(f"{zaehler['abgelehnt']} nicht lesbar")
    return f"{len(liste)} Datei{'en' if len(liste) != 1 else ''} gelesen: " + ", ".join(teile) + "."


@freigabe_berechtigt
def uebersicht(request: FirmaRequest) -> HttpResponse:
    form = KopienUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        ergebnisse = [
            kopien.einlesen(request.firma, datei.name or "rechnung", datei.read(), nutzer=request.user)
            for datei in form.cleaned_data["dateien"]
        ]
        messages.success(request, _zusammenfassung(ergebnisse))
        return redirect("quellen:uebersicht")
    alle = Rechnungskopie.objects.fuer(request.firma).select_related("beleg")
    eintrag = Kopieadresse.objects.fuer(request.firma).first()
    return render(
        request,
        "quellen/uebersicht.html",
        {
            "form": form,
            "adresse": eintrag,
            "adresse_text": kopie_adresse(eintrag),
            "zu_pruefen": alle.filter(status=Rechnungskopie.Status.PRUEFUNG).order_by("-erstellt"),
            "letzte": alle.exclude(status=Rechnungskopie.Status.PRUEFUNG).order_by("-erstellt")[:15],
            **_kontoauszug_kontext(request),
        },
    )


def _kontoauszug_kontext(request: FirmaRequest) -> dict[str, object]:
    firma = request.firma
    alle = Zahlung.objects.fuer(firma).select_related("vorschlag", "vorschlag__kontakt", "beleg")
    return {
        "auszug_form": KontoauszugForm(),
        "stand": zahlungen.stand(firma),
        "auszuege": Kontoauszug.objects.fuer(firma).order_by("-erstellt")[:5],
        "zahlungen_offen": alle.filter(status=Zahlung.Status.NEU).order_by("-buchungsdatum", "pk"),
        "zahlungen_erledigt": alle.exclude(status=Zahlung.Status.NEU).order_by("-erledigt_am")[:10],
        "offene_posten": zahlungen.offene_posten(firma).select_related("kontakt").order_by("nummer")[:300],
    }


@require_POST
@freigabe_berechtigt
def kontoauszug(request: FirmaRequest) -> HttpResponse:
    """K6: Kontoauszug hochladen. Neue Zahlungseingänge bekommen einen Vorschlag; gebucht wird noch nichts."""
    form = KontoauszugForm(request.POST, request.FILES)
    if not form.is_valid():
        for fehler in form.errors.get("datei", ["Bitte eine Datei auswählen."]):
            messages.error(request, str(fehler))
        return redirect("quellen:uebersicht")
    datei = form.cleaned_data["datei"]
    try:
        eintrag = zahlungen.einlesen(request.firma, datei.name or "kontoauszug", datei.read(), request.user)
    except bank.AuszugFehler as fehler:
        messages.error(request, str(fehler))
        return redirect("quellen:uebersicht")
    stand_text = f" mit Stand {eintrag.bis:%d.%m.%Y}" if eintrag.bis else ""
    doppelt = f", {eintrag.doppelt} schon bekannt" if eintrag.doppelt else ""
    messages.success(
        request,
        f"Kontoauszug{stand_text} gelesen: {eintrag.gutschriften} Zahlungseingänge, davon {eintrag.neu} neu{doppelt}. "
        "Abbuchungen werden nicht gespeichert.",
    )
    return redirect(f"{reverse('quellen:uebersicht')}#kontoauszug")


@require_POST
@freigabe_berechtigt
def zahlung(request: FirmaRequest, pk: int) -> HttpResponse:
    """K7: Vorschlag bestätigen, andere Rechnung wählen oder ignorieren. Erst dann ändert sich der Zahlstatus."""
    eintrag = hole_oder_404(Zahlung, request.firma, pk=pk)
    aktion = request.POST.get("aktion", "")
    try:
        if aktion == "ignorieren":
            zahlungen.ignorieren(eintrag, request.user)
            messages.info(request, f"Zahlung über {eintrag.betrag} € ignoriert.")
        else:
            if aktion == "bestaetigen":
                beleg = eintrag.vorschlag
            else:
                beleg = zahlungen.offene_posten(request.firma).filter(pk=_zahl(request.POST.get("beleg"))).first()
            if beleg is None:
                raise zahlungen.ZahlungFehler("Bitte eine offene Rechnung auswählen.")
            ergebnis = zahlungen.bestaetigen(eintrag, beleg, request.user)
            assert ergebnis.beleg is not None
            rest = ergebnis.beleg.offen
            zusatz = "jetzt bezahlt" if rest == 0 else f"noch {rest} € offen"
            messages.success(request, f"Zahlung Rechnung {ergebnis.beleg.nummer} zugeordnet, {zusatz}.")
    except zahlungen.ZahlungFehler as fehler:
        messages.error(request, str(fehler))
    return redirect(f"{reverse('quellen:uebersicht')}#kontoauszug")


def _zahl(wert: str | None) -> int:
    return int(wert) if wert and wert.isdigit() else 0


@require_POST
@freigabe_berechtigt
def adresse(request: FirmaRequest) -> HttpResponse:
    """Kopie-Adresse anlegen, Absender speichern oder neue Adresse erzeugen (K1)."""
    from .models import _kopie_token

    eintrag, neu = Kopieadresse.objects.get_or_create(firma=request.firma)
    aktion = request.POST.get("aktion", "")
    if aktion == "neue_adresse" and not neu:
        eintrag.token = _kopie_token()
        messages.info(request, "Neue Kopie-Adresse erzeugt. Die alte nimmt keine Mails mehr an.")
    elif aktion == "speichern":
        zeilen = [z.strip().lower() for z in request.POST.get("absender", "").splitlines() if z.strip()]
        eintrag.absender = [z for z in zeilen if "@" in z][:200]
        eintrag.aktiv = bool(request.POST.get("aktiv"))
        messages.success(request, "Kopie-Adresse gespeichert.")
    elif neu:
        messages.success(
            request, "Kopie-Adresse eingerichtet. Tragen Sie jetzt die Absenderadresse Ihres Rechnungsprogramms ein."
        )
    eintrag.save()
    protokolliere(
        request.firma,
        "einstellung.kopieadresse",
        nutzer=request.user,
        objekt=eintrag,
        daten={"aktion": aktion or "anlegen", "aktiv": eintrag.aktiv, "anzahl_absender": len(eintrag.absender)},
    )
    return redirect("quellen:uebersicht")


@freigabe_berechtigt
def kopie(request: FirmaRequest, pk: int) -> HttpResponse:
    """K3/K5: Kopie prüfen. Ein Posten entsteht erst mit „Übernehmen“."""
    eintrag = hole_oder_404(Rechnungskopie, request.firma, pk=pk)
    in_pruefung = eintrag.status == Rechnungskopie.Status.PRUEFUNG
    form = PruefForm(request.POST) if request.method == "POST" else PruefForm.aus_kopie(eintrag.daten)
    if request.method == "POST" and in_pruefung:
        if request.POST.get("aktion") == "verwerfen":
            kopien.verwerfen(eintrag, request.user)
            messages.info(request, "Kopie verworfen. Es wurde kein Posten angelegt.")
            return redirect("quellen:uebersicht")
        if form.is_valid():
            try:
                ergebnis = kopien.uebernehmen(eintrag, form.werte(), request.user)
            except kopien.KopieFehler as fehler:
                form.add_error(None, str(fehler))
            else:
                if ergebnis.status == Rechnungskopie.Status.DOPPELT:
                    messages.info(request, ergebnis.grund)
                else:
                    messages.success(request, f"Rechnung {ergebnis.nummer} übernommen.")
                return redirect("quellen:uebersicht")
    return render(request, "quellen/kopie.html", {"k": eintrag, "form": form, "in_pruefung": in_pruefung})
