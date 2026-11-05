"""Nachgebaute Lexware-API für Tests (respx). Jede Anfrage wird zusätzlich auf `finalize` geprüft."""

import json
from pathlib import Path

import httpx
import respx

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "lexware"
BASIS = "https://api.lexware.io"


def lade(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def pdf() -> bytes:
    return (FIXTURES / "beleg.pdf").read_bytes()


class FinalizeGesendet(AssertionError):
    pass


def finalize_waechter(request: httpx.Request) -> None:
    """Schlägt fehl, sobald irgendeine Anfrage an Lexware `finalize` enthält (harte Regel B5)."""
    if "finalize" in str(request.url).lower():
        raise FinalizeGesendet(f"finalize an Lexware gesendet: {request.method} {request.url}")
    if request.content and b"finalize" in request.content.lower():
        raise FinalizeGesendet("finalize im Request-Body")


def standard_routen(router: respx.Router) -> respx.Router:
    """Lesende Standardantworten im Format der echten API."""
    router.get(f"{BASIS}/v1/profile").respond(200, json=lade("profile.json"))

    def voucherlist(request: httpx.Request) -> httpx.Response:
        status = request.url.params.get("voucherStatus")
        seite = request.url.params.get("page", "0")
        assert request.url.params.get("voucherType") == "invoice,downpaymentinvoice"
        assert request.url.params.get("size") == "250"
        if status == "open":
            return httpx.Response(200, json=lade(f"voucherlist_open_{seite}.json"))
        if status == "overdue":
            return httpx.Response(200, json=lade("voucherlist_overdue_0.json"))
        if status in ("paid,paidoff",):
            return httpx.Response(200, json=lade("voucherlist_paid_0.json"))
        leer = {"content": [], "first": True, "last": True, "totalPages": 0, "totalElements": 0}
        return httpx.Response(200, json=leer)

    router.get(f"{BASIS}/v1/voucherlist").mock(side_effect=voucherlist)
    router.get(f"{BASIS}/v1/contacts").respond(200, json=lade("contacts_0.json"))
    router.get(f"{BASIS}/v1/articles").respond(200, json=lade("articles_0.json"))
    router.get(f"{BASIS}/v1/payments/inv-0002").respond(200, json=lade("payment_open.json"))
    router.get(f"{BASIS}/v1/payments/inv-0900").respond(200, json=lade("payment_paid.json"))
    router.get(f"{BASIS}/v1/invoices/inv-0001").respond(200, json=lade("invoice_0001.json"))
    return router
