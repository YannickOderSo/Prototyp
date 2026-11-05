"""Fehlerklassen der Connectoren. `meldung` ist eine verständliche deutsche Meldung für die Oberfläche."""


class ConnectorFehler(Exception):
    """Basisklasse. `wiederholbar` sagt der Job-Queue, ob ein späterer Versuch sinnvoll ist."""

    wiederholbar = False
    meldung = "Das Bestandstool hat einen Fehler gemeldet."

    def __init__(self, text: str = "", status: int | None = None) -> None:
        super().__init__(text or self.meldung)
        self.status = status


class NichtAutorisiert(ConnectorFehler):
    meldung = "Der API-Schlüssel wurde abgelehnt. Bitte prüfen Sie ihn in Lexware (Tarif XL nötig)."


class NichtGefunden(ConnectorFehler):
    meldung = "Der Beleg wurde im Bestandstool nicht gefunden."


class Validierungsfehler(ConnectorFehler):
    meldung = "Das Bestandstool hat die Daten abgelehnt."


class Konflikt(ConnectorFehler):
    meldung = "Der Beleg wurde inzwischen im Bestandstool geändert."


class RateLimitUeberschritten(ConnectorFehler):
    wiederholbar = True
    meldung = "Das Bestandstool ist gerade ausgelastet. Wir versuchen es später erneut."


class NichtErreichbar(ConnectorFehler):
    wiederholbar = True
    meldung = "Das Bestandstool ist gerade nicht erreichbar. Wir versuchen es später erneut."


class VerboteneOperation(ConnectorFehler):
    """Z. B. der Parameter finalize: Die App legt im Bestandstool nur Entwürfe an (ADR-001, B5)."""

    meldung = "Diese Aktion ist in der App nicht erlaubt."
