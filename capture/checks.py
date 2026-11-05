"""Systemchecks: personenbezogene Daten nur über EU-Endpunkte (ADR-005). Keine US- oder globalen Endpunkte."""

from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, register

EU_HOSTS_MISTRAL = {"api.mistral.ai"}  # Mistral AI, Verarbeitung in der EU


@register()
def eu_endpunkte(app_configs: Any = None, **kwargs: Any) -> list[Error]:
    fehler = []
    region = str(getattr(settings, "BEDROCK_REGION", ""))
    modell = str(getattr(settings, "BEDROCK_MODELL", ""))
    if not region.startswith("eu-"):
        fehler.append(Error(f"BEDROCK_REGION muss eine EU-Region sein, nicht {region!r}.", id="cockpit.E001"))
    if not modell.startswith("eu."):
        fehler.append(
            Error(
                f"BEDROCK_MODELL muss ein EU-Inferenzprofil sein (Präfix 'eu.'), nicht {modell!r}. "
                "'global.' und 'us.' sind verboten.",
                id="cockpit.E002",
            )
        )
    host = urlparse(str(getattr(settings, "MISTRAL_BASIS_URL", ""))).hostname or ""
    if host not in EU_HOSTS_MISTRAL:
        fehler.append(Error(f"MISTRAL_BASIS_URL muss auf die EU-API zeigen, nicht {host!r}.", id="cockpit.E003"))
    return fehler
