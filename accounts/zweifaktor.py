"""Zwei-Faktor-Anmeldung: Einrichtung, Prüfung mit Replay-Schutz, Wiederherstellungscodes."""

from django.db import transaction
from django.utils import timezone

from cockpit.krypto import entschluesseln, verschluesseln

from . import totp
from .codes import code_hash, neuer_code
from .models import Nutzer, ZweiFaktor

ANZAHL_WIEDERHERSTELLUNGSCODES = 10


def einrichtung_beginnen(nutzer: Nutzer) -> ZweiFaktor:
    """Legt ein neues, noch unbestätigtes Geheimnis an (oder liefert das unbestätigte vorhandene)."""
    zf = ZweiFaktor.objects.filter(nutzer=nutzer).first()
    if zf is not None and zf.aktiv:
        raise ValueError("Zwei-Faktor-Anmeldung ist bereits eingerichtet")
    if zf is None:
        zf = ZweiFaktor.objects.create(nutzer=nutzer, geheimnis_verschluesselt=verschluesseln(totp.neues_geheimnis()))
    return zf


def geheimnis(zf: ZweiFaktor) -> str:
    return entschluesseln(zf.geheimnis_verschluesselt)


def code_pruefen(zf: ZweiFaktor, code: str, jetzt: float | None = None) -> bool:
    """Prüft einen TOTP-Code. Jeder Zeitschritt ist nur einmal gültig (Replay-Schutz)."""
    with transaction.atomic():
        gesperrt = ZweiFaktor.objects.select_for_update().get(pk=zf.pk)
        schritt = totp.passender_schritt(geheimnis(gesperrt), code, gesperrt.letzter_schritt, jetzt)
        if schritt is None:
            return False
        gesperrt.letzter_schritt = schritt
        gesperrt.save(update_fields=["letzter_schritt"])
    zf.letzter_schritt = schritt
    return True


def neue_wiederherstellungscodes(zf: ZweiFaktor) -> list[str]:
    codes = [neuer_code(gruppen=2, laenge=5) for _ in range(ANZAHL_WIEDERHERSTELLUNGSCODES)]
    zf.wiederherstellungscodes_hash = [code_hash(c) for c in codes]
    zf.save(update_fields=["wiederherstellungscodes_hash"])
    return codes


def einrichtung_bestaetigen(zf: ZweiFaktor, code: str, jetzt: float | None = None) -> list[str] | None:
    """Bestätigt die Einrichtung mit einem gültigen Code und liefert die Wiederherstellungscodes (einmalig)."""
    if not code_pruefen(zf, code, jetzt):
        return None
    zf.eingerichtet_am = timezone.now()
    zf.save(update_fields=["eingerichtet_am"])
    return neue_wiederherstellungscodes(zf)


def wiederherstellungscode_einloesen(zf: ZweiFaktor, code: str) -> bool:
    gesucht = code_hash(code)
    with transaction.atomic():
        gesperrt = ZweiFaktor.objects.select_for_update().get(pk=zf.pk)
        if gesucht not in gesperrt.wiederherstellungscodes_hash:
            return False
        gesperrt.wiederherstellungscodes_hash = [h for h in gesperrt.wiederherstellungscodes_hash if h != gesucht]
        gesperrt.save(update_fields=["wiederherstellungscodes_hash"])
    zf.wiederherstellungscodes_hash = gesperrt.wiederherstellungscodes_hash
    return True


def aktiver_zweiter_faktor(nutzer: Nutzer) -> ZweiFaktor | None:
    return ZweiFaktor.objects.filter(nutzer=nutzer, eingerichtet_am__isnull=False).first()
