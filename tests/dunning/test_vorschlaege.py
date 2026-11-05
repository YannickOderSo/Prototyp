"""M2-03: Täglicher Vorschlagslauf, idempotent, mit allen Vorbedingungen (D2, D3, D8)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from audit.models import Protokolleintrag
from dunning.models import Mahnplan, Mahnvorschlag
from dunning.vorschlaege import berechnen, vorschlagslauf
from jobs.models import Job
from jobs.queue import enqueue
from tests.dunning.conftest import HEUTE, versendet

pytestmark = pytest.mark.django_db
D = Decimal


def _stufen(firma):
    return {(v.beleg.nummer, v.stufe) for v in Mahnvorschlag.objects.fuer(firma).filter(status="vorgeschlagen")}


def test_erinnerung_ab_tag_7(firma, posten, heute):
    sechs = posten(tage=6)
    sieben = posten(tage=7)
    ergebnis = vorschlagslauf(firma)
    assert [(v.beleg_id, v.stufe) for v in ergebnis.neu] == [(sieben.pk, 0)]
    vorschlag = ergebnis.neu[0]
    assert vorschlag.status == "vorgeschlagen"
    assert vorschlag.zinsen == D("0.00") and vorschlag.pauschale == D("0.00")
    assert vorschlag.gesamt == D("1190.00")
    assert vorschlag.faellig_seit_tagen == 7
    assert not Mahnvorschlag.objects.filter(beleg=sechs).exists()


def test_lauf_ist_idempotent(firma, posten, heute):
    posten(tage=10)
    posten(tage=12)
    assert len(vorschlagslauf(firma).neu) == 2
    zweiter = vorschlagslauf(firma)
    assert zweiter.neu == []
    assert Mahnvorschlag.objects.count() == 2
    assert Protokolleintrag.objects.filter(ereignis="mahnlauf.vorschlaege_erzeugt").count() == 1


def test_lauf_versendet_nie(firma, posten, heute):
    from django.core import mail

    posten(tage=40)
    vorschlagslauf(firma)
    assert mail.outbox == []
    assert not Job.objects.filter(typ__startswith="dunning.versand").exists()
    assert set(Mahnvorschlag.objects.values_list("status", flat=True)) == {"vorgeschlagen"}


def test_ohne_kundentyp_kein_vorschlag_sondern_klaerung(firma, posten, heute):
    ohne = posten(tage=10, kundentyp="unbekannt")
    sammel = posten(tage=10, kundentyp=None)
    ergebnis = vorschlagslauf(firma)
    assert ergebnis.neu == []
    assert {b.pk for b in ergebnis.klaerung} == {ohne.pk, sammel.pk}


def test_pausen(firma, posten, heute):
    beleg_pausiert = posten(tage=10, mahnpause_bis=HEUTE)
    kunde_pausiert = posten(tage=10)
    kunde_pausiert.kontakt.mahnpause_bis = HEUTE + timedelta(days=30)
    kunde_pausiert.kontakt.save()
    pause_vorbei = posten(tage=10, mahnpause_bis=HEUTE - timedelta(days=1))
    ergebnis = vorschlagslauf(firma)
    assert [v.beleg_id for v in ergebnis.neu] == [pause_vorbei.pk]
    assert beleg_pausiert.pk not in {b.pk for b in ergebnis.klaerung}


def test_bezahlt_oder_angebot_kein_vorschlag(firma, posten, heute):
    posten(tage=10, status="bezahlt", offen="0.00", brutto="100.00")
    posten(tage=10, offen="0.00")
    posten(tage=10, art="angebot")
    assert vorschlagslauf(firma).neu == []


def test_abschlagsrechnung_wird_gemahnt(firma, posten, heute):
    posten(tage=10, art="abschlag")
    assert len(vorschlagslauf(firma).neu) == 1


def test_stufe_1_erst_nach_versendeter_erinnerung_mit_abstand(firma, posten, heute):
    ohne_erinnerung = posten(tage=30)  # Erinnerung fehlt → zuerst Stufe 0
    zu_frisch = posten(tage=30)
    versendet(zu_frisch, 0, tage_her=9)
    passt = posten(tage=30)
    versendet(passt, 0, tage_her=10)
    zu_frueh = posten(tage=20)
    versendet(zu_frueh, 0, tage_her=13)
    vorschlagslauf(firma)
    assert _stufen(firma) == {(ohne_erinnerung.nummer, 0), (passt.nummer, 1)}


def test_stufe_2_und_danach_nichts_mehr(firma, posten, heute):
    zweite = posten(tage=40)
    versendet(zweite, 0, tage_her=33)
    versendet(zweite, 1, tage_her=12)
    fertig = posten(tage=80)
    versendet(fertig, 0, tage_her=70)
    versendet(fertig, 1, tage_her=50)
    versendet(fertig, 2, tage_her=30)
    vorschlagslauf(firma)
    assert _stufen(firma) == {(zweite.nummer, 2)}


def test_erinnerung_abgeschaltet(firma, posten, heute):
    Mahnplan.objects.create(firma=firma, erinnerung_aktiv=False)
    posten(tage=20)
    direkt = posten(tage=21)
    vorschlagslauf(firma)
    assert _stufen(firma) == {(direkt.nummer, 1)}


def test_eigene_schwellen(firma, posten, heute):
    Mahnplan.objects.create(firma=firma, tage_erinnerung=14, tage_mahnung1=28, tage_mahnung2=42)
    posten(tage=13)
    b = posten(tage=14)
    vorschlagslauf(firma)
    assert _stufen(firma) == {(b.nummer, 0)}


def test_stufe_1_mit_zinsen_und_pauschale(firma, posten, heute):
    beleg = posten(tage=40, offen="1000.00", brutto="1190.00")  # Teilzahlung: offen < brutto
    versendet(beleg, 0, tage_her=30)
    vorschlag = vorschlagslauf(firma).neu[0]
    assert vorschlag.stufe == 1
    assert vorschlag.offen_betrag == D("1000.00")
    # Erinnerung vor 30 Tagen → Verzug ab Versand + 2 = HEUTE - 28 (früher als Fälligkeit + 30 = HEUTE - 10)
    # 28 Zinstage zu 10,52 %: 1000 × 0,1052 × 28/365 = 8,0701 → 8,07
    assert vorschlag.verzugsbeginn == HEUTE - timedelta(days=28)
    assert vorschlag.zinsen == D("8.07")
    assert vorschlag.pauschale == D("40.00")
    assert vorschlag.gesamt == D("1048.07")
    assert vorschlag.zinsberechnung[0]["tage"] == 28


def test_privatkunde_ohne_pauschale(firma, posten, heute):
    beleg = posten(tage=40, kundentyp="privat", offen="1000.00")
    versendet(beleg, 0, tage_her=30)
    vorschlag = vorschlagslauf(firma).neu[0]
    assert vorschlag.pauschale == D("0.00")
    assert vorschlag.zinsen > 0  # Verzug durch Zugang der Erinnerung


def test_pauschale_nur_einmal(firma, posten, heute):
    beleg = posten(tage=60, offen="1000.00")
    versendet(beleg, 0, tage_her=50)
    v1 = versendet(beleg, 1, tage_her=20, pauschale="40.00")
    assert v1.pauschale == D("40.00")
    vorschlag = vorschlagslauf(firma).neu[0]
    assert vorschlag.stufe == 2
    assert vorschlag.pauschale == D("0.00")
    assert any("bereits" in h for h in vorschlag.hinweise)


def test_ohne_email_postversand(firma, posten, heute):
    posten(tage=10, email="")
    vorschlag = vorschlagslauf(firma).neu[0]
    assert vorschlag.versandart == "post"
    assert any("Postversand nötig" in h for h in vorschlag.hinweise)


def test_ohne_faelligkeit_mit_hinweis(firma, posten, heute):
    beleg = posten(faellig_am=None, belegdatum=HEUTE - timedelta(days=50))
    versendet(beleg, 0, tage_her=20)
    vorschlag = vorschlagslauf(firma).neu[0]
    assert vorschlag.stufe == 1
    assert vorschlag.zinsen == D("0.00") and vorschlag.pauschale == D("0.00")
    assert any("Fälligkeit fehlt" in h for h in vorschlag.hinweise)


def test_offene_vorschlaege_werden_gepflegt(firma, posten, heute):
    bezahlt = posten(tage=10)
    pausiert = posten(tage=10)
    bleibt = posten(tage=40, offen="1000.00")
    versendet(bleibt, 0, tage_her=30)
    vorschlagslauf(firma)
    assert Mahnvorschlag.objects.filter(status="vorgeschlagen").count() == 3
    zinsen_vorher = Mahnvorschlag.objects.get(beleg=bleibt, stufe=1).zinsen
    # am nächsten Tag: bezahlt, pausiert, Zinsen wachsen
    bezahlt.status, bezahlt.offen = "bezahlt", D("0.00")
    bezahlt.save()
    pausiert.mahnpause_bis = HEUTE + timedelta(days=10)
    pausiert.save()
    ergebnis = vorschlagslauf(firma, HEUTE + timedelta(days=1))
    assert Mahnvorschlag.objects.get(beleg=bezahlt).status == "verworfen"
    assert not Mahnvorschlag.objects.filter(beleg=pausiert).exists()
    assert Mahnvorschlag.objects.get(beleg=bleibt, stufe=1).zinsen > zinsen_vorher
    assert ergebnis.aktualisiert == 1
    assert Protokolleintrag.objects.filter(ereignis="mahnvorschlag.zurueckgezogen").exists()


def test_berechnen_speichert_nichts(firma, posten, heute):
    posten(tage=10)
    assert len(berechnen(firma, HEUTE).kandidaten) == 1
    assert not Mahnvorschlag.objects.exists()


def test_fremde_firma_unberuehrt(firma, andere_firma, posten, heute):
    posten(tage=10)
    assert vorschlagslauf(andere_firma).neu == []


def test_zeitplan_verteilt_je_firma(firma, andere_firma, verbindung, posten, heute, worker):
    from cockpit.krypto import verschluesseln
    from connectors.models import Verbindung

    Verbindung.objects.create(firma=andere_firma, schluessel_verschluesselt=verschluesseln("x"))
    Mahnplan.objects.create(firma=andere_firma, automatik_aktiv=False)
    posten(tage=10)
    enqueue("dunning.vorschlaege_alle", {"termin": "2026-11-05T05:00:00+01:00"})
    from tests.conftest import alle_jobs_ausfuehren

    alle_jobs_ausfuehren(worker)
    assert Job.objects.filter(typ="dunning.vorschlaege").count() == 1
    assert Mahnvorschlag.objects.fuer(firma).count() == 1


def test_zeitplan_eintrag():
    from jobs.registry import zeitplan_eintraege

    assert any(e.typ == "dunning.vorschlaege_alle" and e.cron == "0 5 * * *" for e in zeitplan_eintraege())
