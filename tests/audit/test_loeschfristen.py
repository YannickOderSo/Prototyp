"""M4-04: Löschjobs nach Fristen (Sicherheit-Datenschutz-Betrieb.md, E8) und Löschung je Firma."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from django.utils import timezone

from accounts.models import Mitgliedschaft, Nutzer, ZweiFaktor
from audit.loeschfristen import ausfuehren
from audit.models import Protokolleintrag
from capture.models import Datei, Erfassung, PostfachEingang
from capture.services import anlegen
from connectors.models import Verbindung, WebhookEreignis
from dunning.models import Mahnplan, Mahnvorschlag, Versand
from jobs.models import Job, ZeitplanLauf
from jobs.registry import zeitplan_eintraege
from ledger.models import Artikel, Beleg, Kontakt

pytestmark = pytest.mark.django_db
D = Decimal


def _pfad(datei: Datei) -> Path:
    return Path(settings.DATEIABLAGE) / datei.pfad


def _erfassung(firma, inhaber, notiz="Malerarbeiten bei Bau AG"):
    return anlegen(firma, inhaber, "upload", [("aufmass.pdf", b"%PDF-1.7\nInhalt")], notiz=notiz)


def _spiegel(firma):
    kontakt = Kontakt.objects.create(firma=firma, extern_id="k1", name="Bau AG", kundentyp="unternehmer")
    Artikel.objects.create(
        firma=firma, extern_id="a1", bezeichnung="Std", einheit="h", netto=D("50"), steuersatz=D("19"), typ="SERVICE"
    )
    beleg = Beleg.objects.create(
        firma=firma,
        extern_id="b1",
        nummer="RE1",
        kontakt=kontakt,
        offen=D("100"),
        brutto=D("100"),
        status="ueberfaellig",
    )
    vorschlag = Mahnvorschlag.objects.create(firma=firma, beleg=beleg, stufe=0, status="versendet")
    Versand.objects.create(
        firma=firma, vorschlag=vorschlag, empfaenger="buchhaltung@bau.example", betreff="x", text="y"
    )
    return beleg


def test_job_ist_taeglich_eingeplant():
    eintrag = next(e for e in zeitplan_eintraege() if e.typ == "audit.loeschfristen")
    assert eintrag.cron == "30 3 * * *"


def test_rohdateien_nach_7_tagen(firma, inhaber):
    erfassung = _erfassung(firma, inhaber)
    Erfassung.objects.filter(pk=erfassung.pk).update(status=Erfassung.Status.PRUEFUNG)
    datei = erfassung.dateien.get()
    assert _pfad(datei).exists()
    ausfuehren(timezone.now() + timedelta(days=6))
    assert _pfad(datei).exists()
    ausfuehren(timezone.now() + timedelta(days=7, minutes=1))
    datei.refresh_from_db()
    assert not _pfad(datei).exists()
    assert datei.geloescht_am is not None and datei.sha256  # Nachweis bleibt
    erfassung.refresh_from_db()
    assert erfassung.status == Erfassung.Status.PRUEFUNG  # schon aufbereitet: läuft weiter
    eintrag = Protokolleintrag.objects.get(firma=firma, ereignis="loeschfristen.ausgefuehrt")
    assert eintrag.daten == {"rohdateien": 1}


def test_nie_aufbereitete_erfassung_wird_fehler(firma, inhaber):
    erfassung = _erfassung(firma, inhaber)
    assert erfassung.status == Erfassung.Status.WARTET
    ausfuehren(timezone.now() + timedelta(days=8))
    erfassung.refresh_from_db()
    assert erfassung.status == Erfassung.Status.FEHLER
    assert "nach 7 Tagen gelöscht" in erfassung.fehler


def test_erfassungen_nach_12_monaten(firma, inhaber, andere_firma, fremder_inhaber):
    alt = _erfassung(firma, inhaber)
    datei = alt.dateien.get()
    pfad = _pfad(datei)
    Erfassung.objects.filter(pk=alt.pk).update(transkript="Kunde Müller, 3 Stunden", loeschen_ab=timezone.now())
    PostfachEingang.objects.create(message_id="<m1>", firma=firma, ergebnis="angenommen", erfassung=alt)
    neu = _erfassung(firma, inhaber)
    fremd = _erfassung(andere_firma, fremder_inhaber)
    ausfuehren()
    assert not Erfassung.objects.filter(pk=alt.pk).exists()
    assert not Datei.objects.filter(pk=datei.pk).exists()
    assert not pfad.exists()
    assert Erfassung.objects.filter(pk__in=[neu.pk, fremd.pk]).count() == 2
    assert PostfachEingang.objects.get(message_id="<m1>").erfassung is None
    eintrag = Protokolleintrag.objects.get(firma=firma, ereignis="loeschfristen.ausgefuehrt")
    assert eintrag.daten == {"erfassungen": 1}
    assert "Müller" not in str(eintrag.daten)
    assert not Protokolleintrag.objects.filter(firma=andere_firma, ereignis="loeschfristen.ausgefuehrt").exists()


def test_spiegeldaten_30_tage_nach_trennung(firma, verbindung, andere_firma):
    _spiegel(firma)
    _spiegel(andere_firma)
    WebhookEreignis.objects.create(verbindung=verbindung, event_typ="invoice.changed", resource_id="b1", event_zeit="t")
    Verbindung.objects.filter(pk=verbindung.pk).update(
        status=Verbindung.Status.GETRENNT,
        getrennt_am=timezone.now() - timedelta(days=29),
        organisation_id="org-1",
        erstimport_fertig=timezone.now(),
    )
    ausfuehren()
    assert Beleg.objects.fuer(firma).count() == 1  # noch innerhalb der 30 Tage
    ausfuehren(timezone.now() + timedelta(days=1, minutes=1))
    for modell in (Beleg, Kontakt, Artikel, Mahnvorschlag, Versand):
        assert not modell.objects.fuer(firma).exists(), modell
        assert modell.objects.fuer(andere_firma).exists(), modell  # andere Firma unberührt
    assert not WebhookEreignis.objects.filter(verbindung=verbindung).exists()
    verbindung.refresh_from_db()
    assert verbindung.organisation_id == "" and verbindung.erstimport_fertig is None
    eintrag = Protokolleintrag.objects.filter(firma=firma, ereignis="loeschfristen.ausgefuehrt").latest("zeit")
    assert eintrag.daten["belege"] == 1 and eintrag.daten["versaende"] == 1


def test_wieder_verbunden_loescht_nichts(firma, verbindung):
    _spiegel(firma)
    Verbindung.objects.filter(pk=verbindung.pk).update(
        status=Verbindung.Status.AKTIV, getrennt_am=timezone.now() - timedelta(days=60)
    )
    ausfuehren()
    assert Beleg.objects.fuer(firma).exists()


def test_protokoll_nach_8_jahren(firma):
    alt = Protokolleintrag.objects.create(firma=firma, ereignis="alt", zeit=timezone.now() - timedelta(days=8 * 366))
    jung = Protokolleintrag.objects.create(
        firma=firma, ereignis="jung", zeit=timezone.now() - timedelta(days=8 * 365 - 5)
    )
    ausfuehren()
    assert not Protokolleintrag.objects.filter(pk=alt.pk).exists()
    assert Protokolleintrag.objects.filter(pk=jung.pk).exists()


def test_technische_reste(firma, verbindung):
    jetzt = timezone.now()
    erledigt_alt = Job.objects.create(typ="x", status="erledigt", beendet_am=jetzt - timedelta(days=31))
    erledigt_neu = Job.objects.create(typ="x", status="erledigt", beendet_am=jetzt - timedelta(days=5))
    fehler_alt = Job.objects.create(typ="x", status="fehler", beendet_am=jetzt - timedelta(days=91))
    fehler_neu = Job.objects.create(typ="x", status="fehler", beendet_am=jetzt - timedelta(days=31))
    wartet = Job.objects.create(typ="x", status="wartet", erstellt=jetzt - timedelta(days=400))
    ZeitplanLauf.objects.create(name="a", termin=jetzt - timedelta(days=91))
    ZeitplanLauf.objects.create(name="a", termin=jetzt - timedelta(days=1))
    WebhookEreignis.objects.create(
        verbindung=verbindung, event_typ="e", resource_id="1", event_zeit="1", verarbeitet_am=jetzt - timedelta(days=91)
    )
    WebhookEreignis.objects.create(verbindung=verbindung, event_typ="e", resource_id="2", event_zeit="2")
    PostfachEingang.objects.create(message_id="<alt>", ergebnis="abgelehnt", zeit=jetzt - timedelta(days=366))
    PostfachEingang.objects.create(message_id="<neu>", ergebnis="abgelehnt")
    ausfuehren(jetzt)
    assert set(Job.objects.values_list("pk", flat=True)) == {erledigt_neu.pk, fehler_neu.pk, wartet.pk}
    assert erledigt_alt.pk and fehler_alt.pk
    assert ZeitplanLauf.objects.count() == 1
    assert list(WebhookEreignis.objects.values_list("resource_id", flat=True)) == ["2"]
    assert list(PostfachEingang.objects.values_list("message_id", flat=True)) == ["<neu>"]


def test_job_laeuft_ueber_worker(firma, inhaber, worker):
    from jobs.queue import enqueue

    erfassung = _erfassung(firma, inhaber)
    Datei.objects.filter(erfassung=erfassung).update(loeschen_ab=timezone.now() - timedelta(minutes=1))
    Job.objects.all().delete()
    enqueue("audit.loeschfristen", {})
    assert worker.einen_ausfuehren()
    assert Datei.objects.get(erfassung=erfassung).geloescht_am is not None


def test_firma_loeschen_braucht_bestaetigung(firma):
    with pytest.raises(CommandError, match="Bestätigung"):
        call_command("firma_loeschen", firma.pk, "--bestaetigen", "falsch")
    assert firma.__class__.objects.get(pk=firma.pk).aktiv


def test_firma_loeschen(firma, inhaber, freigeber, andere_firma, fremder_inhaber, verbindung):
    _spiegel(firma)
    _spiegel(andere_firma)
    erfassung = _erfassung(firma, inhaber)
    pfad = _pfad(erfassung.dateien.get())
    Mahnplan.objects.create(firma=firma)
    ZweiFaktor.objects.create(nutzer=inhaber, geheimnis_verschluesselt="x")
    ZweiFaktor.objects.create(nutzer=freigeber, geheimnis_verschluesselt="x")
    # Der Freigeber gehört auch zur anderen Firma und bleibt dort aktiv
    Mitgliedschaft.objects.create(nutzer=freigeber, firma=andere_firma, rolle="freigeber")
    Verbindung.objects.filter(pk=verbindung.pk).update(webhook_ids=[])
    call_command("firma_loeschen", firma.pk, "--bestaetigen", firma.name)
    firma.refresh_from_db()
    assert not firma.aktiv and firma.reply_to == "" and firma.name
    for modell in (Erfassung, Beleg, Kontakt, Artikel, Mahnvorschlag, Versand, Verbindung, Mahnplan):
        assert not modell.objects.fuer(firma).exists(), modell
    assert Beleg.objects.fuer(andere_firma).exists()
    assert not pfad.exists()
    assert not Mitgliedschaft.objects.filter(firma=firma).exists()
    inhaber.refresh_from_db()
    freigeber.refresh_from_db()
    assert not inhaber.is_active and not inhaber.has_usable_password()
    assert not ZweiFaktor.objects.filter(nutzer=inhaber).exists()
    assert freigeber.is_active and ZweiFaktor.objects.filter(nutzer=freigeber).exists()
    assert Nutzer.objects.filter(pk=inhaber.pk).exists()  # bleibt als Bezug des Protokolls
    assert Protokolleintrag.objects.filter(firma=firma, ereignis="firma.geloescht").exists()
    assert Protokolleintrag.objects.filter(firma=firma).count() > 1  # Protokoll bleibt
