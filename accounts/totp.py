"""TOTP nach RFC 6238 (HMAC-SHA1, 30 Sekunden, 6 Stellen), eigene Implementierung.

Replay-Schutz: Jeder Zeitschritt wird höchstens einmal akzeptiert (`letzter_schritt`).
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

SCHRITT_SEKUNDEN = 30
STELLEN = 6
TOLERANZ_SCHRITTE = 1  # ±30 Sekunden Uhrabweichung


def neues_geheimnis() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _schluessel(geheimnis: str) -> bytes:
    auffuellen = "=" * (-len(geheimnis) % 8)
    return base64.b32decode(geheimnis.upper() + auffuellen)


def code_fuer_schritt(geheimnis: str, schritt: int, stellen: int = STELLEN, schluessel: bytes | None = None) -> str:
    digest = hmac.new(schluessel or _schluessel(geheimnis), struct.pack(">Q", schritt), hashlib.sha1).digest()
    versatz = digest[-1] & 0x0F
    zahl = struct.unpack(">I", digest[versatz : versatz + 4])[0] & 0x7FFFFFFF
    return str(zahl % 10**stellen).zfill(stellen)


def aktueller_schritt(jetzt: float | None = None) -> int:
    return int((time.time() if jetzt is None else jetzt) // SCHRITT_SEKUNDEN)


def passender_schritt(geheimnis: str, code: str, letzter_schritt: int | None, jetzt: float | None = None) -> int | None:
    """Gibt den Zeitschritt zurück, zu dem der Code passt, oder None. Schritte <= letzter_schritt zählen nicht."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != STELLEN:
        return None
    mitte = aktueller_schritt(jetzt)
    treffer = None
    for schritt in range(mitte - TOLERANZ_SCHRITTE, mitte + TOLERANZ_SCHRITTE + 1):
        if letzter_schritt is not None and schritt <= letzter_schritt:
            continue
        if hmac.compare_digest(code_fuer_schritt(geheimnis, schritt), code):
            treffer = schritt
    return treffer


def provisioning_uri(geheimnis: str, konto: str, aussteller: str = "Forderungs-Cockpit") -> str:
    parameter = urlencode({"secret": geheimnis, "issuer": aussteller, "digits": STELLEN, "period": SCHRITT_SEKUNDEN})
    return f"otpauth://totp/{quote(aussteller)}:{quote(konto)}?{parameter}"
