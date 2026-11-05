"""Jobs der Erfassung."""

from jobs.models import Job
from jobs.registry import job, zeitplan
from jobs.worker import JobAbbruch

from .entwurf import regeln_anwenden
from .extraktion import ExtraktionFehler, extrahieren
from .models import Erfassung
from .pipeline import aufbereiten, fehlgeschlagen
from .transkription import TranskriptionFehler


def _erfassung(j: Job) -> Erfassung:
    erfassung = (
        Erfassung.objects.select_related("firma").filter(pk=j.payload.get("erfassung_id"), firma_id=j.firma_id).first()
    )
    if erfassung is None:
        raise JobAbbruch("Erfassung nicht gefunden")
    return erfassung


@job("capture.aufbereiten")
def _aufbereiten(j: Job) -> None:
    erfassung = _erfassung(j)
    if erfassung.status != Erfassung.Status.WARTET:
        return
    try:
        aufbereiten(erfassung)
    except TranskriptionFehler as fehler:
        if not fehler.wiederholbar or j.versuche + 1 >= j.max_versuche:
            fehlgeschlagen(erfassung, str(fehler))
            raise JobAbbruch(str(fehler)) from fehler
        raise
    if erfassung.kanal == Erfassung.Kanal.MAIL and (erfassung.quellen or erfassung.transkript):
        # Belegpostfach: niemand prüft den Text vorab; geprüft wird in der Prüfansicht vor der Freigabe
        from .services import extraktion_einplanen

        erfassung.status = Erfassung.Status.EXTRAHIERT
        erfassung.save(update_fields=["status"])
        extraktion_einplanen(erfassung)


def entwurf_bilden(erfassung: Erfassung, ergebnis: dict[str, object], hinweise: list[str]) -> None:
    """Speichert das KI-Ergebnis unverändert und bildet mit den Regeln den prüfbaren Entwurf."""
    erfassung.ki_ergebnis = ergebnis
    erfassung.eingabe = {}
    erfassung.status = Erfassung.Status.PRUEFUNG
    erfassung.save(update_fields=["ki_ergebnis", "eingabe", "status"])
    regeln_anwenden(erfassung, hinweise)


@job("capture.extrahieren")
def _extrahieren(j: Job) -> None:
    erfassung = _erfassung(j)
    if erfassung.status != Erfassung.Status.EXTRAHIERT:
        return
    try:
        ergebnis, hinweise = extrahieren(erfassung)
    except ExtraktionFehler as fehler:
        if not fehler.wiederholbar or j.versuche + 1 >= j.max_versuche:
            fehlgeschlagen(erfassung, str(fehler))
            raise JobAbbruch(str(fehler)) from fehler
        raise
    entwurf_bilden(erfassung, ergebnis, hinweise)


@job("capture.uebertragen")
def _uebertragen(j: Job) -> None:
    from connectors.fehler import ConnectorFehler

    from .uebertragung import uebertragen, zurueck_zur_pruefung

    erfassung = _erfassung(j)
    try:
        uebertragen(erfassung)
    except ConnectorFehler as fehler:
        if not fehler.wiederholbar or j.versuche + 1 >= j.max_versuche:
            zurueck_zur_pruefung(erfassung, f"Lexware: {fehler.meldung} ({fehler})")
            raise JobAbbruch(str(fehler)) from fehler
        raise
    except ValueError as fehler:
        zurueck_zur_pruefung(erfassung, str(fehler))
        raise JobAbbruch(str(fehler)) from fehler


@job("capture.postfach_abrufen")
def _postfach(j: Job) -> None:
    from .postfach import abrufen

    abrufen()


zeitplan("belegpostfach", "*/5 * * * *", "capture.postfach_abrufen", max_versuche=1)
