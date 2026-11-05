"""M7-02: Angebote im Spiegel mit Ablaufdatum und Status angenommen/abgelehnt (I3, ADR-009)."""

from datetime import date

import httpx
import pytest
import time_machine

from ledger.abgleich import angebote_abgleichen
from ledger.models import Beleg
from tests.lexware_mock import BASIS

pytestmark = pytest.mark.django_db


def _eintrag(id_, status, nummer, datum="2026-10-20", geaendert="2026-10-21T08:00:00.000+02:00"):
    return {
        "id": id_,
        "voucherType": "quotation",
        "voucherStatus": status,
        "voucherNumber": nummer,
        "voucherDate": f"{datum}T00:00:00.000+02:00",
        "updatedDate": geaendert,
        "dueDate": None,
        "contactId": None,
        "contactName": "Bau AG",
        "totalAmount": 1190.0,
        "openAmount": None,
    }


@pytest.fixture
def angebote_api(lexware_api):
    eintraege = [
        _eintrag("q-offen", "open", "AN-1"),
        _eintrag("q-an", "accepted", "AN-2"),
        _eintrag("q-ab", "rejected", "AN-3"),
    ]

    def liste(request: httpx.Request) -> httpx.Response:
        assert request.url.params["voucherType"] == "quotation"
        assert request.url.params["voucherStatus"] == "open,accepted,rejected"
        assert request.url.params["voucherDateFrom"] == "2025-11-05"
        return httpx.Response(200, json={"content": eintraege, "first": True, "last": True, "totalPages": 1})

    lexware_api.get(f"{BASIS}/v1/voucherlist").mock(side_effect=liste)
    detail = lexware_api.get(f"{BASIS}/v1/quotations/q-offen").respond(
        200, json={"id": "q-offen", "voucherStatus": "open", "expirationDate": "2026-11-09T00:00:00.000+01:00"}
    )
    return eintraege, detail


@time_machine.travel(date(2026, 11, 5))
def test_status_und_gueltigkeit(firma, verbindung, lexware, angebote_api):
    eintraege, detail = angebote_api
    assert angebote_abgleichen(verbindung, lexware) == 3
    status = dict(Beleg.objects.filter(firma=firma).values_list("nummer", "status"))
    assert status == {"AN-1": "offen", "AN-2": "angenommen", "AN-3": "abgelehnt"}
    offen = Beleg.objects.get(firma=firma, nummer="AN-1")
    assert offen.gueltig_bis == date(2026, 11, 9) and offen.offen == 0
    assert detail.call_count == 1
    # Zweiter Lauf ohne Änderung in Lexware: kein erneuter Detailabruf
    angebote_abgleichen(verbindung, lexware)
    assert detail.call_count == 1
    # Geändert in Lexware: Detail wird neu geladen
    eintraege[0]["updatedDate"] = "2026-11-04T08:00:00.000+01:00"
    angebote_abgleichen(verbindung, lexware)
    assert detail.call_count == 2


@time_machine.travel(date(2026, 11, 5))
def test_geloeschtes_offenes_angebot_wird_storniert(firma, verbindung, lexware, angebote_api):
    Beleg.objects.create(
        firma=firma, extern_id="q-weg", art="angebot", nummer="AN-0", status="offen", belegdatum=date(2026, 9, 1)
    )
    Beleg.objects.create(
        firma=firma, extern_id="q-alt", art="angebot", nummer="AN-ALT", status="offen", belegdatum=date(2025, 1, 1)
    )
    angebote_abgleichen(verbindung, lexware)
    assert Beleg.objects.get(extern_id="q-weg").status == "storniert"
    assert Beleg.objects.get(extern_id="q-alt").status == "offen"  # außerhalb des Zeitraums: unberührt


def test_get_quotation_nicht_gefunden(lexware, lexware_api):
    lexware_api.get(f"{BASIS}/v1/quotations/fehlt").respond(404)
    assert lexware.get_quotation("fehlt") is None
