"""Verschlüsselung von Geheimnissen (API-Schlüssel, TOTP, SMTP) mit MultiFernet.

Der erste Schlüssel in COCKPIT_FERNET_KEYS verschlüsselt, alle Schlüssel entschlüsseln.
Rotation: neuen Schlüssel vorne einfügen, `manage.py schluessel_rotieren` ausführen, alten entfernen.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings


class EntschluesselungFehlgeschlagen(Exception):
    pass


@lru_cache(maxsize=1)
def _fernet(schluessel: tuple[str, ...]) -> MultiFernet:
    if not schluessel:
        raise RuntimeError("COCKPIT_FERNET_KEYS ist leer")
    return MultiFernet([Fernet(s.encode() if isinstance(s, str) else s) for s in schluessel])


def _aktuell() -> MultiFernet:
    return _fernet(tuple(settings.FERNET_KEYS))


def verschluesseln(klartext: str) -> str:
    return _aktuell().encrypt(klartext.encode()).decode()


def entschluesseln(geheimtext: str) -> str:
    try:
        return _aktuell().decrypt(geheimtext.encode()).decode()
    except InvalidToken as fehler:
        raise EntschluesselungFehlgeschlagen("Geheimnis kann nicht entschlüsselt werden") from fehler


def neu_verschluesseln(geheimtext: str) -> str:
    """Verschlüsselt mit dem aktuell ersten Schlüssel neu (für die Rotation)."""
    return _aktuell().rotate(geheimtext.encode()).decode()
