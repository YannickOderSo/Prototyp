"""Wöchentliche Sammelfreigabe-Mail (D6, M2-07).

Die Mail enthält nur eine Übersicht und einen Link ins Cockpit. Der Link trägt kein Token: Wer ihn öffnet,
muss sich mit Passwort und zweitem Faktor anmelden und dort freigeben (ADR-004).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import Firma, Mitgliedschaft, Rolle
from audit.services import protokolliere

from .mail import euro
from .models import Mahnplan, Mahnvorschlag, Sammelmail
from .services import mahnplan_fuer
from .vorschlaege import klaerung_noetig

ABSCHNITTE: list = []  # weitere Abschnitte (z. B. Wochenbericht, F1) registrieren sich hier


def iso_woche(tag: datetime) -> str:
    jahr, woche, _ = tag.isocalendar()
    return f"{jahr}-W{woche:02d}"


def termin_dieser_woche(plan: Mahnplan, jetzt_lokal: datetime) -> datetime:
    montag = (jetzt_lokal - timedelta(days=jetzt_lokal.weekday())).date()
    tag = montag + timedelta(days=plan.wochentag_freigabe)
    return datetime.combine(tag, plan.uhrzeit_freigabe, tzinfo=jetzt_lokal.tzinfo)


def faellig(firma: Firma, jetzt: datetime | None = None) -> bool:
    """Am eingestellten Wochentag ab der eingestellten Uhrzeit, höchstens einmal je Woche."""
    zone = ZoneInfo(firma.zeitzone or settings.TIME_ZONE)
    lokal = (jetzt or timezone.now()).astimezone(zone)
    termin = termin_dieser_woche(mahnplan_fuer(firma), lokal)
    if lokal.date() != termin.date() or lokal < termin:
        return False
    return not Sammelmail.objects.fuer(firma).filter(woche=iso_woche(lokal)).exists()


def empfaenger(firma: Firma) -> list[str]:
    return sorted(
        Mitgliedschaft.objects.filter(
            firma=firma, rolle__in=[Rolle.INHABER, Rolle.FREIGEBER], nutzer__is_active=True
        ).values_list("nutzer__email", flat=True)
    )


def inhalt(firma: Firma, jetzt: datetime | None = None) -> tuple[str, str, int]:
    jetzt = jetzt or timezone.now()
    offen = Mahnvorschlag.objects.fuer(firma).filter(status=Mahnvorschlag.Status.VORGESCHLAGEN)
    zeilen = []
    anzahl = 0
    for stufe, label in Mahnvorschlag.Stufe.choices:
        liste = offen.filter(stufe=stufe)
        if liste.exists():
            summe = sum((v.gesamt for v in liste), Decimal("0.00"))
            zeilen.append(f"- {label}: {liste.count()} (zusammen {euro(summe)})")
            anzahl += liste.count()
    klaerung = len(klaerung_noetig(firma, timezone.localdate(jetzt)))
    link = settings.BASIS_URL + reverse("dunning:freigabe")
    if anzahl:
        betreff = (
            f"{anzahl} Erinnerung{'en' if anzahl != 1 else ''} und Mahnung{'en' if anzahl != 1 else ''} zur Freigabe"
        )
        text = "Guten Morgen,\n\ndiese Woche liegen zur Freigabe bereit:\n" + "\n".join(zeilen) + "\n"
    else:
        betreff = "Diese Woche keine Mahnungen zur Freigabe"
        text = "Guten Morgen,\n\ndiese Woche liegen keine Erinnerungen oder Mahnungen zur Freigabe vor.\n"
    if klaerung:
        text += f"\nBei {klaerung} überfälligen Posten fehlt der Kundentyp; diese werden nicht gemahnt.\n"
    text += (
        f"\nZur Freigabe im Cockpit (Anmeldung mit Passwort und Zwei-Faktor-Code nötig):\n{link}\n\n"
        "Aus Sicherheitsgründen gibt dieser Link selbst nichts frei.\n"
    )
    for abschnitt in ABSCHNITTE:
        text += abschnitt(firma, jetzt)
    return f"{firma.name}: {betreff}", text, anzahl


def senden(firma: Firma, jetzt: datetime | None = None) -> Sammelmail | None:
    jetzt = jetzt or timezone.now()
    zone = ZoneInfo(firma.zeitzone or settings.TIME_ZONE)
    adressen = empfaenger(firma)
    if not adressen:
        return None
    betreff, text, anzahl = inhalt(firma, jetzt)
    try:
        with transaction.atomic():
            lauf = Sammelmail.objects.create(
                firma=firma, woche=iso_woche(jetzt.astimezone(zone)), empfaenger=adressen, anzahl_vorschlaege=anzahl
            )
            EmailMessage(betreff, text, to=adressen).send(fail_silently=False)
    except IntegrityError:
        return None  # in dieser Woche bereits versendet
    protokolliere(firma, "sammelmail.versendet", objekt=lauf, daten={"woche": lauf.woche, "vorschlaege": anzahl})
    return lauf
