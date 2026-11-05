"""Systemcheck: Fehlererfassung nur mit EU-Datenhaltung (ADR-005, keine US-Endpunkte)."""

from typing import Any

from django.conf import settings
from django.core.checks import Error, register

from cockpit.fehlererfassung import erlaubter_host


@register()
def fehlererfassung_eu(app_configs: Any = None, **kwargs: Any) -> list[Error]:
    dsn = str(getattr(settings, "SENTRY_DSN", ""))
    if dsn and not erlaubter_host(dsn):
        return [
            Error(
                "SENTRY_DSN muss auf eine EU-Instanz zeigen (GlitchTip selbst gehostet oder *.de.sentry.io).",
                id="cockpit.E004",
            )
        ]
    return []
