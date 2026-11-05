"""M6-04/05: Kunden und Artikel in Lexware anlegen (Format laut Doku), Rechnungsadresse spiegeln."""

import json
from decimal import Decimal

import httpx

from connectors.base import ArticleDraft, ContactDraft
from tests.lexware_mock import BASIS


def test_firma_mit_adresse_und_mail(lexware, lexware_api):
    route = lexware_api.post(f"{BASIS}/v1/contacts").respond(200, json={"id": "neu-1", "version": 1})
    extern_id = lexware.create_contact(
        ContactDraft(
            name="Bau AG",
            ist_firma=True,
            email="info@bau.example",
            strasse="Hauptstr. 1",
            plz="12345",
            ort="Musterstadt",
            notiz="Kundennummer aus Excel: K-17",
        )
    )
    assert extern_id == "neu-1"
    koerper = json.loads(route.calls.last.request.content)
    assert koerper == {
        "version": 0,
        "roles": {"customer": {}},
        "company": {"name": "Bau AG"},
        "addresses": {
            "billing": [{"street": "Hauptstr. 1", "zip": "12345", "city": "Musterstadt", "countryCode": "DE"}]
        },
        "emailAddresses": {"business": ["info@bau.example"]},
        "note": "Kundennummer aus Excel: K-17",
    }
    assert "finalize" not in str(route.calls.last.request.url)


def test_person_ohne_adresse(lexware, lexware_api):
    route = lexware_api.post(f"{BASIS}/v1/contacts").respond(200, json={"id": "neu-2"})
    lexware.create_contact(ContactDraft(name="Musterfrau", vorname="Erika", ist_firma=False))
    koerper = json.loads(route.calls.last.request.content)
    assert koerper["person"] == {"lastName": "Musterfrau", "firstName": "Erika"}
    assert "company" not in koerper and "addresses" not in koerper


def test_artikel_mit_dezimalpreis_ohne_float(lexware, lexware_api):
    route = lexware_api.post(f"{BASIS}/v1/articles").respond(200, json={"id": "art-neu"})
    lexware.create_article(
        ArticleDraft(
            bezeichnung="Malerstunde",
            typ="SERVICE",
            einheit="Stunde",
            netto=Decimal("58.10"),
            steuersatz=Decimal("19"),
            artikelnummer="M-1",
        )
    )
    roh = route.calls.last.request.content.decode()
    assert '"netPrice": 58.10' in roh  # Decimal bleibt exakt
    koerper = json.loads(roh)
    assert koerper["price"]["leadingPrice"] == "NET" and koerper["price"]["taxRate"] == 19
    assert koerper["type"] == "SERVICE" and koerper["unitName"] == "Stunde" and koerper["articleNumber"] == "M-1"


def test_rechnungsadresse_wird_gelesen(lexware, lexware_api):
    lexware_api.get(f"{BASIS}/v1/contacts/k-adr").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "k-adr",
                "roles": {"customer": {"number": 10001}},
                "company": {"name": "Huber GmbH"},
                "addresses": {
                    "billing": [
                        {
                            "supplement": "Hinterhaus",
                            "street": "Weg 2",
                            "zip": "80331",
                            "city": "München",
                            "countryCode": "DE",
                        }
                    ]
                },
            },
        )
    )
    kontakt = lexware.get_contact("k-adr")
    assert kontakt.adresse == "Hinterhaus\nWeg 2\n80331 München"
