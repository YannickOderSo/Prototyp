"""M3-08: Übertragung als Entwurf in Lexware (E7, B5). Nie finalize; nur Inhaber und Freigeber geben frei."""

import json
from decimal import Decimal

import pytest
from django.urls import reverse

from audit.models import Protokolleintrag
from capture.entwurf import regeln_anwenden
from capture.models import Erfassung
from ledger.models import Artikel, Kontakt
from tests.conftest import alle_jobs_ausfuehren
from tests.ki_fake import ergebnis
from tests.lexware_mock import BASIS, lade

pytestmark = pytest.mark.django_db


@pytest.fixture
def bereit(firma, verbindung, mitarbeiter):
    Kontakt.objects.create(firma=firma, extern_id="kon-unternehmer", name="Bau AG")
    Artikel.objects.create(
        firma=firma,
        extern_id="art-maler-stunde",
        bezeichnung="Malerarbeiten Facharbeiter",
        einheit="Stunde",
        netto=Decimal("58.00"),
        steuersatz=Decimal("19"),
        typ="SERVICE",
    )
    ki = ergebnis(
        positionen=[
            {
                "artikel_id": "art-maler-stunde",
                "beschreibung": "Malerarbeiten",
                "menge": 12.5,
                "einheit": "Stunde",
                "quelle": "Sprachmemo",
                "herkunft": "gesprochen",
            },
            {
                "artikel_id": "",
                "beschreibung": "Sondermaß-Rahmen",
                "menge": 2,
                "einheit": "Stück",
                "quelle": "Foto 1",
                "herkunft": "foto",
            },
        ]
    )
    e = Erfassung.objects.create(
        firma=firma, erstellt_von=mitarbeiter, kanal="aufnahme", status="pruefung", ki_ergebnis=ki
    )
    regeln_anwenden(e)
    e.eingabe["positionen"][1].update({"preis_nutzer": "85.50", "steuersatz_nutzer": "19"})
    e.save()
    regeln_anwenden(e)
    assert e.blocker == []
    return e


def test_rechnungsentwurf_in_lexware(client_freigeber, freigeber, bereit, lexware_api, ohne_warten, worker):
    route = lexware_api.post(f"{BASIS}/v1/invoices").respond(201, json=lade("created.json"))
    antwort = client_freigeber.post(reverse("capture:freigeben", args=[bereit.pk]))
    assert antwort.status_code == 302
    alle_jobs_ausfuehren(worker)
    bereit.refresh_from_db()
    assert bereit.status == "uebertragen"
    assert bereit.ziel_extern_id == "neu-0001"
    assert bereit.ziel_url == "https://app.lexware.de/permalink/invoices/edit/neu-0001"
    anfrage = route.calls.last.request
    assert "finalize" not in str(anfrage.url)
    body = json.loads(anfrage.content)
    assert body["address"] == {"contactId": "kon-unternehmer"}
    assert body["lineItems"][0] == {
        "type": "service",
        "id": "art-maler-stunde",
        "name": "Malerarbeiten",
        "quantity": 12.5,
        "unitName": "Stunde",
        "unitPrice": {"currency": "EUR", "taxRatePercentage": 19, "netAmount": 58.00},
    }
    assert body["lineItems"][1]["type"] == "custom"
    assert body["lineItems"][1]["unitPrice"]["netAmount"] == 85.50
    assert body["shippingConditions"]["shippingType"] == "serviceperiod"
    assert Protokolleintrag.objects.get(ereignis="erfassung.freigegeben").nutzer == freigeber
    assert Protokolleintrag.objects.get(ereignis="lexware.entwurf_angelegt").daten == {
        "art": "invoice",
        "id": "neu-0001",
    }
    html = client_freigeber.get(reverse("capture:detail", args=[bereit.pk])).content.decode()
    assert "Entwurf in Lexware öffnen" in html


def test_angebotsentwurf(client_inhaber, bereit, lexware_api, ohne_warten, worker):
    bereit.eingabe["belegart"] = "angebot"
    bereit.save()
    regeln_anwenden(bereit)
    route = lexware_api.post(f"{BASIS}/v1/quotations").respond(201, json=lade("created.json"))
    client_inhaber.post(reverse("capture:freigeben", args=[bereit.pk]))
    alle_jobs_ausfuehren(worker)
    body = json.loads(route.calls.last.request.content)
    assert "expirationDate" in body
    bereit.refresh_from_db()
    assert bereit.ziel_art == "quotation"


def test_nie_finalize_bei_allen_uebertragungen(client_inhaber, bereit, lexware_api, ohne_warten, worker):
    lexware_api.post(f"{BASIS}/v1/invoices").respond(201, json=lade("created.json"))
    client_inhaber.post(reverse("capture:freigeben", args=[bereit.pk]))
    alle_jobs_ausfuehren(worker)
    assert lexware_api.calls
    for aufruf in lexware_api.calls:
        assert "finalize" not in str(aufruf.request.url).lower()
        assert b"finalize" not in (aufruf.request.content or b"").lower()


def test_mitarbeiter_darf_nicht_freigeben(client_mitarbeiter, bereit):
    assert client_mitarbeiter.post(reverse("capture:freigeben", args=[bereit.pk])).status_code == 403
    bereit.refresh_from_db()
    assert bereit.status == "pruefung"


def test_mit_blockern_keine_freigabe(client_inhaber, bereit):
    bereit.eingabe["positionen"][1].pop("preis_nutzer")
    bereit.save()
    antwort = client_inhaber.post(reverse("capture:freigeben", args=[bereit.pk]), follow=True)
    assert "offene Punkte" in antwort.content.decode()
    bereit.refresh_from_db()
    assert bereit.status == "pruefung"


def test_ohne_freigabe_nichts_an_lexware(client, bereit, lexware_api):
    client.post(reverse("capture:freigeben", args=[bereit.pk]))
    assert not lexware_api.calls


def test_lexware_lehnt_ab_zurueck_zur_pruefung(client_inhaber, bereit, lexware_api, ohne_warten, worker):
    lexware_api.post(f"{BASIS}/v1/invoices").respond(400, json={"message": "contact has no customer role"})
    client_inhaber.post(reverse("capture:freigeben", args=[bereit.pk]))
    alle_jobs_ausfuehren(worker)
    bereit.refresh_from_db()
    assert bereit.status == "pruefung"
    assert "Lexware" in bereit.fehler
    assert bereit.freigegeben_von is None


def test_doppelte_ausfuehrung_legt_nur_einen_entwurf_an(client_inhaber, bereit, lexware_api, ohne_warten, worker):
    from capture.uebertragung import uebertragen

    route = lexware_api.post(f"{BASIS}/v1/invoices").respond(201, json=lade("created.json"))
    client_inhaber.post(reverse("capture:freigeben", args=[bereit.pk]))
    alle_jobs_ausfuehren(worker)
    bereit.refresh_from_db()
    assert uebertragen(bereit) is None
    assert route.call_count == 1
