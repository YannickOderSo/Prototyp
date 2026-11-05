"""Audio für den Telefonassistenten (ADR-010, J7): Sprechpausen erkennen, WAV bauen, Spracherkennung, Sprachausgabe.

Telefonaudio aus Asterisk (AudioSocket): 16 Bit signed little-endian, 8 kHz, mono, 20-ms-Pakete (320 Byte).
Spracherkennung: Mistral Voxtral (EU) je Beitrag. Sprachausgabe: Piper, selbst gehostet; nichts verlässt den Server.
"""

from __future__ import annotations

import io
import json
import math
import subprocess
import wave
from array import array
from pathlib import Path
from typing import Protocol

from django.conf import settings

ABTASTRATE = 8000
RAHMEN_BYTES = 320  # 20 ms bei 8 kHz und 16 Bit


def als_wav(pcm: bytes, rate: int = ABTASTRATE) -> bytes:
    puffer = io.BytesIO()
    with wave.open(puffer, "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(rate)
        datei.writeframes(pcm)
    return puffer.getvalue()


def pegel(rahmen: bytes) -> float:
    """Effektivwert (RMS) eines 16-Bit-Rahmens."""
    werte = array("h")
    werte.frombytes(rahmen[: len(rahmen) - len(rahmen) % 2])
    if not werte:
        return 0.0
    return math.sqrt(sum(w * w for w in werte) / len(werte))


def umrechnen(pcm: bytes, von: int, nach: int = ABTASTRATE) -> bytes:
    """Abtastrate per linearer Interpolation umrechnen (16 Bit mono). Für kurze Ansagen schnell genug."""
    if von == nach:
        return pcm
    quelle = array("h")
    quelle.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if not quelle:
        return b""
    laenge = int(len(quelle) * nach / von)
    ziel = array("h", bytes(2 * laenge))
    faktor = von / nach
    letzte = len(quelle) - 1
    for i in range(laenge):
        pos = i * faktor
        links = int(pos)
        rechts = min(links + 1, letzte)
        anteil = pos - links
        ziel[i] = int(quelle[links] * (1 - anteil) + quelle[rechts] * anteil)
    return ziel.tobytes()


class Sprechpausen:
    """Einfache Sprechpausen-Erkennung über den Pegel (kein Barge-in, Prototyp).

    Ein Beitrag beginnt nach `min_sprache` lauten Rahmen und endet nach `stille_ende` leisen Rahmen oder nach
    `max_rahmen`. Zurückgegeben wird der Beitrag samt kurzem Vorlauf.
    """

    def __init__(
        self,
        schwelle: float = 500.0,
        min_sprache: int = 8,
        stille_ende: int = 40,
        max_rahmen: int = 1000,
        vorlauf: int = 10,
    ) -> None:
        self.schwelle, self.min_sprache, self.stille_ende = schwelle, min_sprache, stille_ende
        self.max_rahmen, self.vorlauf = max_rahmen, vorlauf
        self.zuruecksetzen()

    def zuruecksetzen(self) -> None:
        self._vor: list[bytes] = []
        self._beitrag: list[bytes] = []
        self._laut = 0
        self._still = 0
        self._spricht = False

    def rahmen(self, rahmen: bytes) -> bytes | None:
        laut = pegel(rahmen) >= self.schwelle
        if not self._spricht:
            self._vor = [*self._vor[-self.vorlauf :], rahmen]
            self._laut = self._laut + 1 if laut else 0
            if self._laut >= self.min_sprache:
                self._spricht = True
                self._beitrag = list(self._vor)
                self._still = 0
            return None
        self._beitrag.append(rahmen)
        self._still = 0 if laut else self._still + 1
        if self._still >= self.stille_ende or len(self._beitrag) >= self.max_rahmen:
            beitrag = b"".join(self._beitrag)
            self.zuruecksetzen()
            return beitrag
        return None


def erkennen(pcm: bytes) -> str:
    """Spracherkennung eines Beitrags (Voxtral, EU) – gleiche Anbindung wie bei Sprachmemos."""
    from capture.transkription import transkribieren

    return transkribieren(als_wav(pcm), "beitrag.wav", "audio/wav")


class Sprachausgabe(Protocol):
    def sprechen(self, text: str) -> bytes:
        """Text → 16-Bit-PCM mit 8 kHz."""
        ...


class Piper:
    """Piper TTS als lokaler Prozess (`--output-raw`); die Abtastrate steht in der .onnx.json der Stimme."""

    def __init__(self, befehl: str | None = None, modell: str | None = None) -> None:
        self.befehl = befehl or settings.PIPER_BEFEHL
        self.modell = modell or settings.PIPER_MODELL
        if not self.modell:
            raise ValueError(
                "PIPER_MODELL ist nicht gesetzt (Pfad zur .onnx-Stimme, z. B. de_DE-thorsten-medium.onnx)."
            )
        konfiguration = Path(f"{self.modell}.json")
        self.rate = (
            int(json.loads(konfiguration.read_text())["audio"]["sample_rate"]) if konfiguration.exists() else 22050
        )

    def sprechen(self, text: str) -> bytes:
        ergebnis = subprocess.run(  # noqa: S603 – fester Befehl aus der Einstellung, Text nur über stdin
            [self.befehl, "--model", self.modell, "--output-raw"],
            input=text.encode(),
            capture_output=True,
            timeout=30,
            check=True,
        )
        return umrechnen(ergebnis.stdout, self.rate)


class Stille:
    """Ersatz-Sprachausgabe für Tests und Trockenläufe: Stille, etwa so lang wie gesprochen."""

    def sprechen(self, text: str) -> bytes:
        return bytes(RAHMEN_BYTES * max(1, len(text) // 15))
