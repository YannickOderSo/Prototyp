"""Fehlererfassung (F4) mit GlitchTip (selbst gehostet) oder Sentry mit EU-Datenhaltung.

Keine personenbezogenen Daten: keine Request-Inhalte, Cookies, Header, Query-Strings, lokalen Variablen
und SQL-Parameter; vom Nutzer nur die ID. Endgültig fehlgeschlagene Jobs kommen über das Logging an
(Stufe ERROR), Ausnahmen in Views über die Django-Integration.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit


def erlaubter_host(dsn: str) -> bool:
    """Sentry SaaS nur mit EU-Datenhaltung (`*.de.sentry.io`); eigene Instanzen (GlitchTip) sind erlaubt."""
    host = (urlsplit(dsn).hostname or "").lower()
    if not host:
        return False
    if host == "sentry.io" or host.endswith(".sentry.io"):
        return host.endswith(".de.sentry.io")
    return True


def vor_dem_senden(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    anfrage = event.get("request")
    if isinstance(anfrage, dict):
        url = str(anfrage.get("url", ""))
        teile = urlsplit(url)
        event["request"] = {
            "method": anfrage.get("method"),
            "url": urlunsplit((teile.scheme, teile.netloc, teile.path, "", "")),
        }
    nutzer = event.get("user")
    if isinstance(nutzer, dict):
        event["user"] = {"id": nutzer["id"]} if "id" in nutzer else {}
    krumen = event.get("breadcrumbs")
    if isinstance(krumen, dict) and isinstance(krumen.get("values"), list):
        krumen["values"] = [
            {k: v for k, v in b.items() if k != "data"}
            for b in krumen["values"]
            if isinstance(b, dict) and b.get("category") not in {"query", "httplib", "subprocess"}
        ]
    return event


def einrichten(dsn: str, umgebung: str, version: str | None) -> None:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=dsn,
        integrations=[DjangoIntegration()],
        environment=umgebung,
        release=version,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=0.0,
        before_send=vor_dem_senden,  # type: ignore[arg-type]
    )
