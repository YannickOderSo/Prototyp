"""Transkription mit Mistral Voxtral über die EU-API (ADR-005).

Endpunkt laut Mistral-Doku (geprüft 5. November 2026): POST {MISTRAL_BASIS_URL}/v1/audio/transcriptions,
multipart mit `file`, `model` (Standard `voxtral-mini-latest`) und `language`; Antwort mit `text`.
"""

from __future__ import annotations

import httpx
from django.conf import settings


class TranskriptionFehler(Exception):
    def __init__(self, meldung: str, wiederholbar: bool) -> None:
        super().__init__(meldung)
        self.wiederholbar = wiederholbar


def transkribieren(audio: bytes, name: str, mime: str, client: httpx.Client | None = None) -> str:
    if not settings.MISTRAL_API_KEY:
        raise TranskriptionFehler("Für die Transkription ist kein Mistral-Schlüssel hinterlegt.", wiederholbar=False)
    http = client or httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0))
    try:
        antwort = http.post(
            settings.MISTRAL_BASIS_URL.rstrip("/") + "/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.MISTRAL_API_KEY}"},
            files={"file": (name, audio, mime)},
            data={"model": settings.MISTRAL_MODELL, "language": "de"},
        )
    except httpx.TransportError as fehler:
        raise TranskriptionFehler("Der Transkriptionsdienst ist nicht erreichbar.", wiederholbar=True) from fehler
    if antwort.status_code == 429 or antwort.status_code >= 500:
        raise TranskriptionFehler("Der Transkriptionsdienst ist ausgelastet.", wiederholbar=True)
    if antwort.status_code >= 400:
        raise TranskriptionFehler(
            f"Die Transkription wurde abgelehnt (HTTP {antwort.status_code}).", wiederholbar=False
        )
    return str(antwort.json().get("text") or "").strip()
