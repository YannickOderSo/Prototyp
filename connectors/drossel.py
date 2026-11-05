"""Token-Bucket je Verbindung (Lexware erlaubt 2 Anfragen pro Sekunde über alle Endpunkte, B4)."""

import threading
import time
from collections.abc import Callable


class TokenBucket:
    def __init__(
        self,
        rate: float,
        kapazitaet: float,
        uhr: Callable[[], float] | None = None,
        schlafen: Callable[[float], None] | None = None,
    ) -> None:
        self.rate = rate
        self.kapazitaet = kapazitaet
        # Zur Laufzeit auflösen, damit Tests time.sleep ersetzen können
        self.uhr = uhr or (lambda: time.monotonic())
        self.schlafen = schlafen or (lambda s: time.sleep(s))
        self._token = kapazitaet
        self._zuletzt = self.uhr()
        self._sperre = threading.Lock()

    def _auffuellen(self) -> None:
        jetzt = self.uhr()
        self._token = min(self.kapazitaet, self._token + (jetzt - self._zuletzt) * self.rate)
        self._zuletzt = jetzt

    def nehmen(self) -> float:
        """Wartet, bis ein Token frei ist. Gibt die Wartezeit in Sekunden zurück."""
        gewartet = 0.0
        with self._sperre:
            self._auffuellen()
            while self._token < 1:
                warten = (1 - self._token) / self.rate
                self.schlafen(warten)
                gewartet += warten
                self._auffuellen()
            self._token -= 1
        return gewartet


_EIMER: dict[str, TokenBucket] = {}
_EIMER_SPERRE = threading.Lock()


def eimer_fuer(schluessel: str, rate: float = 2.0, kapazitaet: float = 1.0) -> TokenBucket:
    """Ein Eimer je Verbindung und Prozess. Kapazität 1: keine Bursts, Abstand mindestens 0,5 s."""
    with _EIMER_SPERRE:
        if schluessel not in _EIMER:
            _EIMER[schluessel] = TokenBucket(rate, kapazitaet)
        return _EIMER[schluessel]
