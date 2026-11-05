"""Löschfristen (Sicherheit-Datenschutz-Betrieb.md, Anforderung E8, Ticket M4-04).

Täglich um 3:30 Uhr (nach dem Nachtabgleich, vor dem Vorschlagslauf):

- Rohdateien 7 Tage nach dem Hochladen (`Datei.loeschen_ab`). Audio löscht die Pipeline schon direkt nach der
  Transkription; der Datensatz (Name, Größe, Hash) bleibt als Nachweis.
- Gelesene Zeilen und Vorschau eines Excel-Imports 7 Tage nach dem Hochladen (`ImportVorgang.loeschen_ab`, H9);
  Anzahlen und Ergebnis bleiben als Nachweis. Ein Import, der noch läuft, wird erst nach seinem Ende geleert.
- KI-Telefonassistent (ADR-010): Gesprächsverlauf 90 Tage nach dem Gespräch, Rückruf-Notizen 90 Tage nach
  „erledigt“, offene spätestens nach 12 Monaten.
- Erfassungen samt Transkript, KI-Ergebnis und Entwurf 12 Monate nach dem Anlegen (`Erfassung.loeschen_ab`).
- Spiegeldaten (Kontakte, Artikel, Belege) 30 Tage nach dem Trennen der Verbindung, sofern die Firma nicht wieder
  verbunden ist. Mahnvorschläge und Versände hängen an den Belegen und werden mit gelöscht (Offene-Fragen.md);
  das Protokoll bleibt als Nachweis.
- Protokoll nach 8 Jahren (der Datenbank-Trigger erlaubt das Löschen erst ab dann).
- Technische Reste: erledigte Jobs nach 30 Tagen, fehlgeschlagene Jobs, Zeitplanläufe und verarbeitete
  Webhook-Ereignisse nach 90 Tagen, Postfach-Eingänge und Sammelmail-Nachweise nach 12 Monaten.

Jede Firma bekommt je Lauf höchstens einen Protokolleintrag mit den Anzahlen (keine Inhalte).
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db import connection, models, transaction
from django.utils import timezone

from accounts.models import Firma
from capture.dateien import loeschen as datei_loeschen
from capture.models import Datei, Erfassung, PostfachEingang
from connectors.models import Verbindung, WebhookEreignis
from datenimport.models import ImportVorgang
from dunning.models import Mahnvorschlag, Sammelmail, Versand
from jobs.models import Job, ZeitplanLauf
from ledger.models import Artikel, Beleg, Kontakt
from telefon.models import Gespraech, Rueckruf

from .services import protokolliere

log = logging.getLogger(__name__)

SPIEGEL_NACH_TRENNUNG = timedelta(days=30)
JOBS_ERLEDIGT = timedelta(days=30)
TECHNIK = timedelta(days=90)
NACHWEISE = timedelta(days=365)


@dataclass
class Bericht:
    je_firma: dict[int, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    gesamt: Counter[str] = field(default_factory=Counter)

    def zaehlen(self, firma_id: int | None, art: str, anzahl: int = 1) -> None:
        if anzahl <= 0:
            return
        self.gesamt[art] += anzahl
        if firma_id is not None:
            self.je_firma[firma_id][art] += anzahl


def rohdateien(jetzt: datetime, bericht: Bericht) -> None:
    faellig = Datei.objects.filter(geloescht_am__isnull=True, loeschen_ab__lte=jetzt).order_by("pk")
    betroffen: set[int] = set()
    for datei in faellig.iterator():
        datei_loeschen(datei)
        betroffen.add(datei.erfassung_id)
        bericht.zaehlen(datei.firma_id, "rohdateien")
    # Erfassungen, die nie aufbereitet wurden, können ohne Rohdateien nicht weiterlaufen
    for erfassung in Erfassung.objects.filter(pk__in=betroffen, status=Erfassung.Status.WARTET):
        erfassung.status = Erfassung.Status.FEHLER
        erfassung.fehler = "Die Dateien wurden nach 7 Tagen gelöscht, bevor sie aufbereitet werden konnten."
        erfassung.save(update_fields=["status", "fehler"])


def importzeilen(jetzt: datetime, bericht: Bericht) -> None:
    faellig = (
        ImportVorgang.objects.filter(zeilen_geloescht_am__isnull=True, loeschen_ab__lte=jetzt)
        .exclude(status=ImportVorgang.Status.FREIGEGEBEN)  # läuft noch; braucht die Vorschau
        .order_by("pk")
    )
    for vorgang in faellig.iterator():
        vorgang.ergebnis = {
            **vorgang.ergebnis,
            "anzahl": {s: vorgang.anzahl(s) for s in ("neu", "dublette", "fehler", "bezahlt")},
        }
        vorgang.zeilen, vorgang.vorschau, vorgang.zeilen_geloescht_am = [], [], jetzt
        if vorgang.status in (ImportVorgang.Status.ZUORDNUNG, ImportVorgang.Status.VORSCHAU):
            vorgang.status = ImportVorgang.Status.VERWORFEN  # ohne Zeilen nicht mehr freigebbar
        vorgang.save(update_fields=["ergebnis", "zeilen", "vorschau", "zeilen_geloescht_am", "status"])
        bericht.zaehlen(vorgang.firma_id, "importzeilen")


TELEFON_NOTIZ_NACH_ERLEDIGT = timedelta(days=90)
TELEFON_NOTIZ_HOECHSTENS = timedelta(days=365)


def telefon(jetzt: datetime, bericht: Bericht) -> None:
    """ADR-010: Gesprächsverlauf nach 90 Tagen, Rückruf-Notizen 90 Tage nach Erledigung bzw. nach 12 Monaten."""
    for g in Gespraech.objects.filter(loeschen_ab__lte=jetzt).only("pk", "firma_id").iterator():
        bericht.zaehlen(g.firma_id, "telefon_gespraeche")
    Gespraech.objects.filter(loeschen_ab__lte=jetzt).delete()
    faellig = Rueckruf.objects.filter(
        models.Q(status=Rueckruf.Status.ERLEDIGT, erledigt_am__lte=jetzt - TELEFON_NOTIZ_NACH_ERLEDIGT)
        | models.Q(erstellt__lte=jetzt - TELEFON_NOTIZ_HOECHSTENS)
    )
    for r in faellig.only("pk", "firma_id").iterator():
        bericht.zaehlen(r.firma_id, "rueckrufe")
    faellig.delete()


def erfassungen(jetzt: datetime, bericht: Bericht) -> None:
    for erfassung in Erfassung.objects.filter(loeschen_ab__lte=jetzt).order_by("pk").iterator():
        with transaction.atomic():
            for datei in Datei.objects.filter(erfassung=erfassung, geloescht_am__isnull=True):
                datei_loeschen(datei)
            erfassung.delete()  # Datei-Datensätze hängen per CASCADE daran
        bericht.zaehlen(erfassung.firma_id, "erfassungen")


def spiegel_loeschen(firma: Firma, bericht: Bericht | None = None) -> dict[str, int]:
    """Löscht Spiegeldaten einer Firma samt daran hängender Mahnvorschläge und Versände."""
    anzahlen = {
        "versaende": Versand.objects.fuer(firma).delete()[0],
        "mahnvorschlaege": Mahnvorschlag.objects.fuer(firma).delete()[0],
        "belege": Beleg.objects.fuer(firma).delete()[0],
        "kontakte": Kontakt.objects.fuer(firma).delete()[0],
        "artikel": Artikel.objects.fuer(firma).delete()[0],
    }
    for verbindung in Verbindung.objects.fuer(firma):
        WebhookEreignis.objects.filter(verbindung=verbindung).delete()
    if bericht is not None:
        for art, anzahl in anzahlen.items():
            bericht.zaehlen(firma.pk, art, anzahl)
    return anzahlen


def spiegel_nach_trennung(jetzt: datetime, bericht: Bericht) -> None:
    aktiv = Verbindung.objects.exclude(status=Verbindung.Status.GETRENNT).values("firma_id")
    faellig = (
        Verbindung.objects.filter(status=Verbindung.Status.GETRENNT, getrennt_am__lte=jetzt - SPIEGEL_NACH_TRENNUNG)
        .exclude(firma_id__in=aktiv)
        .select_related("firma")
    )
    for verbindung in faellig:
        with transaction.atomic():
            anzahlen = spiegel_loeschen(verbindung.firma, bericht)
            # Danach darf auch ein anderes Lexware-Konto verbunden werden; ein neuer Erstimport startet leer
            if verbindung.organisation_id or verbindung.erstimport_fertig or any(anzahlen.values()):
                Verbindung.objects.filter(pk=verbindung.pk).update(
                    organisation_id="", firmenname_extern="", erstimport_fertig=None, letzter_abgleich=None
                )


def protokoll(bericht: Bericht) -> None:
    """Gleiche Bedingung wie im Trigger (Datenbankzeit), damit der Trigger nie widerspricht."""
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM audit_protokolleintrag WHERE zeit < now() - interval '8 years' RETURNING firma_id")
        for (firma_id,) in cursor.fetchall():
            bericht.zaehlen(firma_id, "protokolleintraege")


def technik(jetzt: datetime, bericht: Bericht) -> None:
    bericht.zaehlen(
        None, "jobs", Job.objects.filter(status=Job.Status.ERLEDIGT, beendet_am__lt=jetzt - JOBS_ERLEDIGT).delete()[0]
    )
    bericht.zaehlen(
        None, "jobs", Job.objects.filter(status=Job.Status.FEHLER, beendet_am__lt=jetzt - TECHNIK).delete()[0]
    )
    bericht.zaehlen(None, "zeitplanlaeufe", ZeitplanLauf.objects.filter(termin__lt=jetzt - TECHNIK).delete()[0])
    bericht.zaehlen(
        None,
        "webhook_ereignisse",
        WebhookEreignis.objects.filter(verarbeitet_am__lt=jetzt - TECHNIK).delete()[0],
    )
    bericht.zaehlen(None, "postfach_eingaenge", PostfachEingang.objects.filter(zeit__lt=jetzt - NACHWEISE).delete()[0])
    bericht.zaehlen(None, "sammelmails", Sammelmail.objects.filter(gesendet_am__lt=jetzt - NACHWEISE).delete()[0])


def ausfuehren(jetzt: datetime | None = None) -> Bericht:
    jetzt = jetzt or timezone.now()
    bericht = Bericht()
    rohdateien(jetzt, bericht)
    importzeilen(jetzt, bericht)
    telefon(jetzt, bericht)
    erfassungen(jetzt, bericht)
    spiegel_nach_trennung(jetzt, bericht)
    protokoll(bericht)
    technik(jetzt, bericht)
    for firma in Firma.objects.filter(pk__in=list(bericht.je_firma)):
        protokolliere(firma, "loeschfristen.ausgefuehrt", daten=dict(sorted(bericht.je_firma[firma.pk].items())))
    log.info("Löschfristen ausgeführt", extra={"anzahlen": dict(bericht.gesamt)})
    return bericht


def firma_loeschen(firma: Firma) -> dict[str, int]:
    """Löschung einer Firma auf Verlangen (Betroffenenrechte, Admin-Kommando `firma_loeschen`).

    Löscht alle fachlichen Daten. Bleiben: das Protokoll (8 Jahre, Nachweis), der Firmendatensatz als
    Bezug des Protokolls (nur Name, inaktiv) und Nutzer, die im Protokoll stehen (deaktiviert, ohne
    Passwort und zweiten Faktor), sofern sie keiner anderen Firma angehören.
    """
    from accounts.models import Mitgliedschaft, Nutzer, TeamEinladung, ZweiFaktor
    from capture.models import Belegpostfach, KiVerbrauch
    from connectors.fehler import ConnectorFehler
    from connectors.services import trennen
    from dunning.models import Mahnplan, SmtpZugang

    for verbindung in Verbindung.objects.fuer(firma).exclude(status=Verbindung.Status.GETRENNT):
        try:
            trennen(verbindung, None, "Firma gelöscht")  # meldet Webhooks ab, löscht den Schlüssel
        except ConnectorFehler:
            log.warning("Firma löschen: Trennen fehlgeschlagen", extra={"firma_id": firma.pk})
    anzahlen: dict[str, int] = {}
    with transaction.atomic():
        for erfassung in Erfassung.objects.fuer(firma):
            for datei in Datei.objects.filter(erfassung=erfassung, geloescht_am__isnull=True):
                datei_loeschen(datei)
        anzahlen["erfassungen"] = Erfassung.objects.fuer(firma).delete()[0]
        anzahlen.update(spiegel_loeschen(firma))
        for name, queryset in (
            ("verbindungen", Verbindung.objects.fuer(firma)),
            ("belegpostfach", Belegpostfach.objects.fuer(firma)),
            ("postfach_eingaenge", PostfachEingang.objects.filter(firma=firma)),
            ("ki_verbrauch", KiVerbrauch.objects.fuer(firma)),
            ("mahnplan", Mahnplan.objects.fuer(firma)),
            ("smtp", SmtpZugang.objects.fuer(firma)),
            ("sammelmails", Sammelmail.objects.fuer(firma)),
            ("team_einladungen", TeamEinladung.objects.filter(firma=firma)),
            ("jobs", Job.objects.filter(firma=firma)),
            ("importe", ImportVorgang.objects.fuer(firma)),
            ("rueckrufe", Rueckruf.objects.fuer(firma)),
            ("gespraeche", Gespraech.objects.fuer(firma)),
        ):
            anzahlen[name] = queryset.delete()[0]
        nutzer_ids = list(Mitgliedschaft.objects.filter(firma=firma).values_list("nutzer_id", flat=True))
        anzahlen["mitgliedschaften"] = Mitgliedschaft.objects.filter(firma=firma).delete()[0]
        ohne_firma = Nutzer.objects.filter(pk__in=nutzer_ids).exclude(mitgliedschaften__isnull=False)
        ZweiFaktor.objects.filter(nutzer__in=ohne_firma).delete()
        for nutzer in ohne_firma:
            nutzer.is_active = False
            nutzer.set_unusable_password()
            nutzer.save()
        anzahlen["nutzer_deaktiviert"] = len(ohne_firma)
        for feld in ("strasse", "plz", "ort", "email_absender", "reply_to", "mahn_signatur", "bankverbindung"):
            setattr(firma, feld, "")
        firma.aktiv = False
        firma.save()
        protokolliere(firma, "firma.geloescht", objekt=firma, daten=anzahlen)
    return anzahlen
