"""Zufällige Codes und deren Hashes (Einladungen, Team-Links, Wiederherstellungscodes).

Die Codes haben mindestens 80 Bit Zufall; deshalb genügt SHA-256 ohne Salz und Stretching.
"""

import hashlib
import secrets

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # ohne 0/O und 1/I


def neuer_code(gruppen: int = 4, laenge: int = 4) -> str:
    return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(laenge)) for _ in range(gruppen))


def normalisiere(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def code_hash(code: str) -> str:
    return hashlib.sha256(normalisiere(code).encode()).hexdigest()


def neues_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
