"""M1-05: LexwareConnector gegen nachgebaute Antworten im Format der echten API."""

from datetime import date
from decimal import Decimal

import httpx
import pytest

from connectors.base import DraftLine, DunningFees, ExternalRef, InvoiceDraft, QuotationDraft, geld
from connectors.drossel import TokenBucket
from connectors.fehler import (
    NichtAutorisiert,
    NichtErreichbar,
    RateLimitUeberschritten,
    Validierungsfehler,
    VerboteneOperation,
)
from connectors.lexware import LexwareConnector, als_json, zeitpunkt
from tests.lexware_mock import BASIS, lade, pdf


def test_profil(lexware):
    info = lexware.test()
    assert info.firmenname == "Malerbetrieb Muster GmbH"
    assert info.organisation_id == "aa93e8a8-2aa3-470b-b914-caad8a255dd8"
    assert info.steuerart == "net"


def test_authorization_header(lexware, lexware_api):
    lexware.test()
    assert lexware_api.calls.last.request.headers["Authorization"] == "Bearer test-schluessel"


def test_offene_posten_mit_paging_und_ueberfaelligen(lexware):
    posten = list(lexware.list_open_receivables())
    assert [p.extern_id for p in posten] == ["inv-0001", "inv-0002", "dpi-0003", "inv-0004", "inv-0005"]
    teilbezahlt = posten[1]
    assert teilbezahlt.brutto == Decimal("99.80")
    assert teilbezahlt.offen == Decimal("74.80")
    assert isinstance(teilbezahlt.offen, Decimal)
    assert posten[0].faellig_am == date(2026, 11, 3)
    assert posten[0].belegdatum == date(2026, 10, 20)
    assert posten[2].art == "abschlag"
    assert posten[3].status == "ueberfaellig"
    assert posten[4].faellig_am is None
    assert posten[4].kontakt_extern_id is None


def test_inkrementell_mit_updated_date_from(lexware, lexware_api):
    list(lexware.list_receivables("any", date(2026, 11, 4)))
    params = lexware_api.calls.last.request.url.params
    assert params["updatedDateFrom"] == "2026-11-04"
    assert params["voucherStatus"] == "any"


def test_zahlstatus(lexware):
    offen = lexware.get_payment_status("inv-0002")
    assert offen.offen == Decimal("74.80")
    assert not offen.bezahlt
    assert offen.zahlungen == ((date(2026, 10, 30), Decimal("25.00")),)
    bezahlt = lexware.get_payment_status("inv-0900")
    assert bezahlt.bezahlt
    assert bezahlt.bezahlt_am == date(2026, 6, 30)


def test_zahlstatus_entwurf_406_ist_kein_fehler(lexware, lexware_api):
    lexware_api.get(f"{BASIS}/v1/payments/entwurf").respond(406, json={"message": "draft"})
    status = lexware.get_payment_status("entwurf")
    assert status.status == "entwurf"
    assert not status.bezahlt


def test_kontakte(lexware):
    kontakte = {k.extern_id: k for k in lexware.list_contacts()}
    assert kontakte["kon-unternehmer"].name == "Bau AG"
    assert kontakte["kon-unternehmer"].email == "rechnung@bau-ag.example"
    assert kontakte["kon-unternehmer"].kundennummer == "10001"
    assert kontakte["kon-unternehmer"].ist_unternehmen is True
    assert kontakte["kon-privat"].name == "Erika Musterfrau"
    assert kontakte["kon-privat"].email == "erika@example.org"
    assert kontakte["kon-privat"].ist_unternehmen is False
    assert kontakte["kon-ohne-mail"].email == ""


def test_artikel(lexware):
    artikel = {a.extern_id: a for a in lexware.list_articles()}
    assert artikel["art-maler-stunde"].netto == Decimal("58.00")
    assert artikel["art-maler-stunde"].steuersatz == Decimal("19")
    assert artikel["art-maler-stunde"].typ == "SERVICE"
    assert artikel["art-farbe"].einheit == "Eimer"
    assert artikel["art-brutto"].netto == Decimal("30.00")  # 35,70 brutto / 1,19


def test_einzelnen_beleg_nachladen(lexware, lexware_api):
    lexware_api.get(f"{BASIS}/v1/payments/inv-0001").respond(
        200, json={**lade("payment_open.json"), "openAmount": 1190.0}
    )
    posten = lexware.get_receivable("inv-0001")
    assert posten.nummer == "RE1001"
    assert posten.kontakt_extern_id == "kon-unternehmer"
    assert posten.brutto == Decimal("1190.00")
    assert posten.offen == Decimal("1190.00")
    assert posten.faellig_am == date(2026, 11, 3)


def test_unbekannter_beleg(lexware, lexware_api):
    lexware_api.get(f"{BASIS}/v1/invoices/weg").respond(404)
    lexware_api.get(f"{BASIS}/v1/down-payment-invoices/weg").respond(404)
    assert lexware.get_receivable("weg") is None


# --------------------------------------------------------------- Rate-Limit und Fehler
def test_429_wird_mit_backoff_wiederholt(lexware, lexware_api, ohne_warten):
    route = lexware_api.get(f"{BASIS}/v1/contacts/k1")
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(429, headers={"Retry-After": "3"}),
        httpx.Response(200, json={"id": "k1", "person": {"lastName": "A"}}),
    ]
    assert lexware.get_contact("k1").name == "A"
    assert route.call_count == 3
    assert len(ohne_warten) == 2
    assert 1 <= ohne_warten[0] <= 1.25
    assert ohne_warten[1] >= 3


def test_5xx_und_netzwerkfehler_werden_wiederholt(lexware, lexware_api):
    route = lexware_api.get(f"{BASIS}/v1/contacts/k2")
    route.side_effect = [httpx.Response(503), httpx.ConnectError("weg"), httpx.Response(200, json={"id": "k2"})]
    assert lexware.get_contact("k2").extern_id == "k2"


def test_dauerhaft_429_gibt_wiederholbaren_fehler(lexware, lexware_api):
    lexware_api.get(f"{BASIS}/v1/contacts/k3").respond(429)
    with pytest.raises(RateLimitUeberschritten) as fehler:
        lexware.get_contact("k3")
    assert fehler.value.wiederholbar
    assert lexware_api.routes[-1].call_count == 6


def test_dauerhaft_500(lexware, lexware_api):
    lexware_api.get(f"{BASIS}/v1/contacts/k4").respond(500)
    with pytest.raises(NichtErreichbar):
        lexware.get_contact("k4")


@pytest.mark.parametrize(
    ("status", "fehlerklasse"),
    [(401, NichtAutorisiert), (402, NichtAutorisiert), (400, Validierungsfehler), (406, Validierungsfehler)],
)
def test_nicht_wiederholbare_fehler(lexware, lexware_api, status, fehlerklasse):
    route = lexware_api.get(f"{BASIS}/v1/profile").respond(status)
    with pytest.raises(fehlerklasse):
        lexware.test()
    assert route.call_count == 1


def test_404_bei_kontakt(lexware, lexware_api):
    lexware_api.get(f"{BASIS}/v1/contacts/x").respond(404)
    assert lexware.get_contact("x") is None


def test_token_bucket_haelt_zwei_pro_sekunde():
    uhr = [0.0]
    pausen = []

    def schlafen(s):
        pausen.append(s)
        uhr[0] += s

    eimer = TokenBucket(rate=2.0, kapazitaet=1.0, uhr=lambda: uhr[0], schlafen=schlafen)
    for _ in range(5):
        eimer.nehmen()
    assert uhr[0] == pytest.approx(2.0)  # 5 Anfragen brauchen mindestens 2 Sekunden
    assert all(p == pytest.approx(0.5) for p in pausen)


def test_lasttest_500_rechnungen_ohne_abbruch(ohne_warten):
    """B4: 500 Rechnungen über 2 Seiten mit eingestreuten 429 laufen durch."""
    import respx

    eintraege = [
        {**lade("voucherlist_open_0.json")["content"][0], "id": f"inv-{i:04d}", "voucherNumber": f"RE{i}"}
        for i in range(500)
    ]
    antworten = [
        httpx.Response(429),
        httpx.Response(200, json={"content": eintraege[:250], "last": False, "totalPages": 2}),
        httpx.Response(429),
        httpx.Response(429),
        httpx.Response(200, json={"content": eintraege[250:], "last": True, "totalPages": 2}),
    ]
    with respx.mock() as router:
        router.get(f"{BASIS}/v1/voucherlist").side_effect = antworten
        connector = LexwareConnector("k", eimer=TokenBucket(1000, 1000), schlafen=lambda s: None)
        posten = list(connector.list_receivables("open"))
    assert len(posten) == 500
    assert len({p.extern_id for p in posten}) == 500


# --------------------------------------------------------------- Entwürfe, nie finalize
def _entwurf_positionen():
    return (
        DraftLine(
            "Malerarbeiten Facharbeiter",
            Decimal("12.5"),
            "Stunde",
            Decimal("58.00"),
            Decimal("19"),
            "art-maler-stunde",
            "SERVICE",
        ),
        DraftLine("Dispersionsfarbe", Decimal("3"), "Eimer", Decimal("49.90"), Decimal("19"), "art-farbe", "PRODUCT"),
    )


def test_rechnungsentwurf_ohne_finalize(lexware, lexware_api):
    route = lexware_api.post(f"{BASIS}/v1/invoices").respond(201, json=lade("created.json"))
    ref = lexware.create_invoice_draft(
        InvoiceDraft("kon-unternehmer", date(2026, 11, 5), _entwurf_positionen(), date(2026, 11, 2), date(2026, 11, 4))
    )
    assert ref == ExternalRef("invoice", "neu-0001", "https://app.lexware.de/permalink/invoices/edit/neu-0001")
    anfrage = route.calls.last.request
    assert "finalize" not in str(anfrage.url)
    body = anfrage.content.decode()
    assert '"netAmount": 58.00' in body
    assert '"quantity": 12.5' in body
    daten = __import__("json").loads(body)
    assert daten["address"] == {"contactId": "kon-unternehmer"}
    assert daten["lineItems"][0]["type"] == "service"
    assert daten["lineItems"][0]["id"] == "art-maler-stunde"
    assert daten["lineItems"][1]["type"] == "material"
    assert daten["shippingConditions"]["shippingType"] == "serviceperiod"
    assert daten["voucherDate"] == "2026-11-05T00:00:00.000+01:00"
    assert daten["taxConditions"] == {"taxType": "net"}


def test_angebotsentwurf(lexware, lexware_api):
    route = lexware_api.post(f"{BASIS}/v1/quotations").respond(201, json=lade("created.json"))
    lexware.create_quotation_draft(
        QuotationDraft("kon-privat", date(2026, 11, 5), date(2026, 12, 5), _entwurf_positionen())
    )
    daten = __import__("json").loads(route.calls.last.request.content)
    assert daten["expirationDate"] == "2026-12-05T00:00:00.000+01:00"
    assert "finalize" not in str(route.calls.last.request.url)


def test_mahnungsentwurf_mit_zinsen_und_pauschale(lexware, lexware_api):
    route = lexware_api.post(f"{BASIS}/v1/dunnings").respond(201, json={**lade("created.json"), "id": "mahn-1"})
    ref = lexware.create_dunning_draft(
        "inv-0001",
        DunningFees(1, "RE1001", Decimal("1190.00"), Decimal("12.34"), Decimal("40.00"), belegdatum=date(2026, 12, 10)),
    )
    assert ref.art == "dunning"
    assert ref.extern_id == "mahn-1"
    anfrage = route.calls.last.request
    assert anfrage.url.params["precedingSalesVoucherId"] == "inv-0001"
    daten = __import__("json").loads(anfrage.content)
    assert daten["address"] == {"contactId": "kon-unternehmer"}
    assert daten["taxConditions"] == {"taxType": "net"}  # wie in der Rechnung
    namen = [p["name"] for p in daten["lineItems"]]
    assert namen[0].startswith("Offener Betrag aus Rechnung RE1001: 1.190,00 €")
    zinsen = next(p for p in daten["lineItems"] if p["name"].startswith("Verzugszinsen"))
    assert zinsen["unitPrice"] == {"currency": "EUR", "taxRatePercentage": 0, "netAmount": 12.34}
    assert any(p["name"].startswith("Verzugspauschale") for p in daten["lineItems"])


def test_mahnungsentwurf_ohne_gebuehren(lexware, lexware_api):
    route = lexware_api.post(f"{BASIS}/v1/dunnings").respond(201, json=lade("created.json"))
    lexware.create_dunning_draft("inv-0001", DunningFees(1, "RE1001", Decimal("1190.00")))
    daten = __import__("json").loads(route.calls.last.request.content)
    assert [p["type"] for p in daten["lineItems"]] == ["text"]


def test_pdf(lexware, lexware_api):
    route = lexware_api.get(f"{BASIS}/v1/dunnings/mahn-1/file").respond(
        200, content=pdf(), headers={"Content-Type": "application/pdf"}
    )
    inhalt = lexware.get_pdf(ExternalRef("dunning", "mahn-1"))
    assert inhalt.startswith(b"%PDF")
    assert route.calls.last.request.headers["Accept"] == "application/pdf"
    lexware_api.get(f"{BASIS}/v1/invoices/inv-0001/file").respond(200, content=b"<html>")
    with pytest.raises(Validierungsfehler):
        lexware.get_pdf(ExternalRef("invoice", "inv-0001"))


def test_webhooks_registrieren_und_loeschen(lexware, lexware_api):
    route = lexware_api.post(f"{BASIS}/v1/event-subscriptions").respond(
        201, json=lade("event_subscription_created.json")
    )
    ids = lexware.register_webhooks("https://cockpit.example/hooks/lexware/tok")
    assert len(ids) == route.call_count
    ereignisse = {__import__("json").loads(c.request.content)["eventType"] for c in route.calls}
    assert {
        "invoice.status.changed",
        "payment.changed",
        "invoice.created",
        "contact.changed",
        "token.revoked",
    } <= ereignisse
    loeschen = lexware_api.delete(url__regex=rf"{BASIS}/v1/event-subscriptions/.+").respond(204)
    lexware.delete_webhooks(["a", "b"])
    assert loeschen.call_count == 2


# --------------------------------------------------------------- finalize ist verboten
@pytest.mark.parametrize(
    ("pfad", "params"),
    [
        ("/v1/invoices?finalize=true", None),
        ("/v1/invoices", {"finalize": "true"}),
        ("/v1/quotations", {"FINALIZE": True}),
    ],
)
def test_finalize_wird_vor_dem_senden_verweigert(lexware, lexware_api, pfad, params):
    with pytest.raises(VerboteneOperation):
        lexware._anfrage("POST", pfad, params=params, daten={})
    assert not lexware_api.calls


def test_alle_schreibenden_methoden_senden_nie_finalize(lexware, lexware_api):
    """Harte Regel: über alle Requests aller schreibenden Methoden hinweg kein finalize."""
    lexware_api.post(f"{BASIS}/v1/invoices").respond(201, json=lade("created.json"))
    lexware_api.post(f"{BASIS}/v1/quotations").respond(201, json=lade("created.json"))
    lexware_api.post(f"{BASIS}/v1/dunnings").respond(201, json=lade("created.json"))
    lexware_api.post(f"{BASIS}/v1/event-subscriptions").respond(201, json=lade("event_subscription_created.json"))
    lexware.create_invoice_draft(InvoiceDraft("k", date(2026, 11, 5), _entwurf_positionen()))
    lexware.create_quotation_draft(QuotationDraft("k", date(2026, 11, 5), date(2026, 12, 5), _entwurf_positionen()))
    lexware.create_dunning_draft("inv-0001", DunningFees(2, "RE1001", Decimal("1"), Decimal("2"), Decimal("40")))
    lexware.register_webhooks("https://x.example/hook")
    assert lexware_api.calls
    for aufruf in lexware_api.calls:
        assert "finalize" not in str(aufruf.request.url).lower()
        assert b"finalize" not in (aufruf.request.content or b"").lower()


def test_quelltext_enthaelt_kein_finalize_true():
    """Statische Prüfung: kein Modul der App setzt finalize=true."""
    from pathlib import Path

    wurzel = Path(__file__).resolve().parents[2]
    for datei in wurzel.glob("*/**/*.py"):
        if any(teil in datei.parts for teil in (".venv", "tests", "migrations")):
            continue
        text = datei.read_text(encoding="utf-8").lower().replace(" ", "")
        assert "finalize=true" not in text, datei
        assert '"finalize":true' not in text, datei


# --------------------------------------------------------------- Hilfsfunktionen
def test_geld_ohne_float():
    assert geld(0.1 + 0.2) == Decimal("0.30")
    assert geld("2.345") == Decimal("2.35")  # ROUND_HALF_UP
    assert geld(None) == Decimal("0.00")


def test_json_mit_decimal_als_zahl():
    assert als_json({"a": Decimal("1.10"), "b": [Decimal("-2")], "c": "x"}) == '{"a": 1.10, "b": [-2], "c": "x"}'


def test_zeitpunkt_sommer_und_winterzeit():
    assert zeitpunkt(date(2026, 7, 1)) == "2026-07-01T00:00:00.000+02:00"
    assert zeitpunkt(date(2026, 12, 1)) == "2026-12-01T00:00:00.000+01:00"


def test_leerer_schluessel():
    with pytest.raises(NichtAutorisiert):
        LexwareConnector("")
