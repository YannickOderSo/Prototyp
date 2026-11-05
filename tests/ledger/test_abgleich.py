"""M1-07: Erstimport und nächtlicher Abgleich in den Spiegel (B2, B3 Teil Abgleich)."""

from datetime import date
from decimal import Decimal

import httpx
import pytest
from django.db.models import Sum
from django.urls import reverse

from connectors.models import Verbindung
from jobs.models import Job
from jobs.queue import enqueue
from ledger.models import Artikel, Beleg, Kontakt
from tests.conftest import alle_jobs_ausfuehren
from tests.lexware_mock import BASIS, lade

# Summe und Anzahl der offenen Posten in den nachgebauten Lexware-Antworten
ERWARTET_SUMME = Decimal("1190.00") + Decimal("74.80") + Decimal("2380.00") + Decimal("5000.00") + Decimal("450.50")
ERWARTET_ANZAHL = 5


def _offene(firma):
    return Beleg.objects.fuer(firma).filter(status__in=Beleg.OFFENE_STATUS, offen__gt=0)


@pytest.mark.django_db
def test_verbinden_startet_erstimport_und_summen_stimmen(client_inhaber, firma, lexware_api, ohne_warten, worker):
    client_inhaber.post(reverse("connectors:lexware"), {"schluessel": "abc"})
    assert Job.objects.filter(typ="ledger.erstimport", firma=firma).exists()
    alle_jobs_ausfuehren(worker)
    offen = _offene(firma)
    assert offen.count() == ERWARTET_ANZAHL
    assert offen.aggregate(s=Sum("offen"))["s"] == ERWARTET_SUMME  # Abweichung 0 (B2)
    assert Kontakt.objects.fuer(firma).count() == 3
    assert Artikel.objects.fuer(firma).count() == 3
    verbindung = Verbindung.objects.get(firma=firma)
    assert verbindung.erstimport_fertig is not None
    # Zahlungshistorie läuft als Folge-Job
    bezahlt = Beleg.objects.get(firma=firma, extern_id="inv-0900")
    assert bezahlt.status == Beleg.Status.BEZAHLT
    assert bezahlt.bezahlt_am == date(2026, 6, 30)
    assert not Job.objects.filter(status__in=["wartet", "fehler"]).exists()


@pytest.mark.django_db
def test_spiegel_details(firma, verbindung, lexware_api, ohne_warten, worker):
    enqueue("ledger.erstimport", {"verbindung_id": verbindung.pk}, firma=firma)
    alle_jobs_ausfuehren(worker)
    beleg = Beleg.objects.get(firma=firma, extern_id="inv-0002")
    assert beleg.nummer == "RE1002"
    assert beleg.offen == Decimal("74.80")
    assert beleg.brutto == Decimal("99.80")
    assert beleg.kontakt.name == "Erika Musterfrau"
    assert beleg.kontakt.kundentyp == "unbekannt"  # Kundentyp wird nie aus Lexware übernommen (D3)
    sammel = Beleg.objects.get(firma=firma, extern_id="inv-0005")
    assert sammel.kontakt is None
    assert sammel.faellig_am is None
    assert Beleg.objects.get(firma=firma, extern_id="dpi-0003").art == "abschlag"


@pytest.mark.django_db
def test_kundentyp_bleibt_beim_abgleich_erhalten(firma, verbindung, lexware_api, ohne_warten, worker):
    enqueue("ledger.erstimport", {"verbindung_id": verbindung.pk}, firma=firma)
    alle_jobs_ausfuehren(worker)
    Kontakt.objects.filter(firma=firma, extern_id="kon-privat").update(kundentyp="privat", notiz="ruft gern an")
    enqueue("ledger.nachtabgleich", {"verbindung_id": verbindung.pk}, firma=firma)
    alle_jobs_ausfuehren(worker)
    kontakt = Kontakt.objects.get(firma=firma, extern_id="kon-privat")
    assert kontakt.kundentyp == "privat"
    assert kontakt.notiz == "ruft gern an"


@pytest.mark.django_db
def test_nachtabgleich_laedt_verschwundene_offene_posten_einzeln(firma, verbindung, lexware_api, ohne_warten, worker):
    enqueue("ledger.erstimport", {"verbindung_id": verbindung.pk}, firma=firma)
    alle_jobs_ausfuehren(worker)
    # inv-0001 wurde in Lexware bezahlt, Webhook verpasst: taucht in der Offen-Liste nicht mehr auf
    ohne_0001 = lade("voucherlist_open_0.json")
    ohne_0001["content"] = ohne_0001["content"][1:]

    def voucherlist(request):
        status = request.url.params.get("voucherStatus")
        if status == "open":
            if request.url.params.get("page") == "0":
                return httpx.Response(200, json=ohne_0001)
            return httpx.Response(200, json=lade("voucherlist_open_1.json"))
        if status == "overdue":
            return httpx.Response(200, json=lade("voucherlist_overdue_0.json"))
        return httpx.Response(200, json={"content": [], "last": True, "totalPages": 0})

    lexware_api.get(f"{BASIS}/v1/voucherlist").mock(side_effect=voucherlist)
    lexware_api.get(f"{BASIS}/v1/invoices/inv-0001").respond(
        200, json={**lade("invoice_0001.json"), "voucherStatus": "paid"}
    )
    lexware_api.get(f"{BASIS}/v1/payments/inv-0001").respond(
        200, json={**lade("payment_paid.json"), "paidDate": "2026-11-04T10:00:00.000+01:00"}
    )
    enqueue("ledger.nachtabgleich", {"verbindung_id": verbindung.pk}, firma=firma)
    alle_jobs_ausfuehren(worker)
    beleg = Beleg.objects.get(firma=firma, extern_id="inv-0001")
    assert beleg.status == Beleg.Status.BEZAHLT
    assert beleg.offen == Decimal("0.00")
    assert beleg.bezahlt_am == date(2026, 11, 4)
    assert _offene(firma).count() == ERWARTET_ANZAHL - 1


@pytest.mark.django_db
def test_nachtabgleich_inkrementell_ab_letztem_abgleich_minus_ein_tag(
    firma, verbindung, lexware_api, ohne_warten, worker
):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    Verbindung.objects.filter(pk=verbindung.pk).update(
        letzter_abgleich=datetime(2026, 11, 4, 2, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    )
    enqueue("ledger.nachtabgleich", {"verbindung_id": verbindung.pk}, firma=firma)
    alle_jobs_ausfuehren(worker)
    any_aufrufe = [c for c in lexware_api.calls if c.request.url.params.get("voucherStatus") == "any"]
    assert any_aufrufe[0].request.url.params["updatedDateFrom"] == "2026-11-03"


@pytest.mark.django_db
def test_abgelehnter_schluessel_setzt_verbindung_auf_fehler(firma, verbindung, lexware_api, ohne_warten, worker):
    lexware_api.get(f"{BASIS}/v1/contacts").respond(401)
    job = enqueue("ledger.erstimport", {"verbindung_id": verbindung.pk}, firma=firma)
    alle_jobs_ausfuehren(worker)
    job.refresh_from_db()
    verbindung.refresh_from_db()
    assert job.status == Job.Status.FEHLER
    assert job.versuche == 1  # nicht wiederholt
    assert verbindung.status == Verbindung.Status.FEHLER
    assert "abgelehnt" in verbindung.fehler


@pytest.mark.django_db
def test_lexware_nicht_erreichbar_wird_wiederholt(firma, verbindung, lexware_api, ohne_warten, worker):
    lexware_api.get(f"{BASIS}/v1/contacts").respond(503)
    job = enqueue("ledger.erstimport", {"verbindung_id": verbindung.pk}, firma=firma)
    worker.einen_ausfuehren()
    job.refresh_from_db()
    assert job.status == Job.Status.WARTET
    assert job.versuche == 1
    assert "nicht erreichbar" in Verbindung.objects.get(pk=verbindung.pk).fehler


@pytest.mark.django_db
def test_nachtabgleich_alle_verteilt_je_verbindung(firma, andere_firma, verbindung, worker):
    from cockpit.krypto import verschluesseln

    Verbindung.objects.create(firma=andere_firma, schluessel_verschluesselt=verschluesseln("x"))
    Verbindung.objects.create(firma=andere_firma, typ="sevdesk", status="getrennt")
    enqueue("ledger.nachtabgleich_alle")
    worker.einen_ausfuehren()
    jobs = Job.objects.filter(typ="ledger.nachtabgleich")
    assert jobs.count() == 2
    assert {j.firma_id for j in jobs} == {firma.pk, andere_firma.pk}


@pytest.mark.django_db
def test_job_fuer_fremde_firma_wird_abgebrochen(firma, andere_firma, verbindung, worker):
    job = enqueue("ledger.erstimport", {"verbindung_id": verbindung.pk}, firma=andere_firma)
    worker.einen_ausfuehren()
    job.refresh_from_db()
    assert job.status == Job.Status.FEHLER


def test_nachtabgleich_im_zeitplan():
    from jobs.registry import zeitplan_eintraege

    assert any(e.typ == "ledger.nachtabgleich_alle" and e.cron == "0 2 * * *" for e in zeitplan_eintraege())
