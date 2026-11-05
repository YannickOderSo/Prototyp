"""Hilfen für Tests gegen einen laufenden Mailpit-Server (lokal per Docker, in CI als Service)."""

import os

import httpx
import pytest

MAILPIT_URL = os.environ.get("MAILPIT_URL", "")
SMTP_HOST = os.environ.get("MAILPIT_SMTP_HOST", "127.0.0.1")
SMTP_PORT = int(os.environ.get("MAILPIT_SMTP_PORT", "1025"))

braucht_mailpit = pytest.mark.skipif(not MAILPIT_URL, reason="MAILPIT_URL nicht gesetzt (Mailpit läuft nicht)")


def leeren() -> None:
    httpx.delete(f"{MAILPIT_URL}/api/v1/messages", timeout=10)


def nachrichten() -> list[dict]:
    daten = httpx.get(f"{MAILPIT_URL}/api/v1/messages", timeout=10).json()
    return [httpx.get(f"{MAILPIT_URL}/api/v1/message/{m['ID']}", timeout=10).json() for m in daten.get("messages", [])]


def kopfzeilen(message_id: str) -> dict:
    return httpx.get(f"{MAILPIT_URL}/api/v1/message/{message_id}/headers", timeout=10).json()


def smtp_einstellungen() -> dict:
    return {
        "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "EMAIL_HOST": SMTP_HOST,
        "EMAIL_PORT": SMTP_PORT,
        "EMAIL_USE_TLS": False,
        "EMAIL_HOST_USER": "",
        "EMAIL_HOST_PASSWORD": "",
    }
