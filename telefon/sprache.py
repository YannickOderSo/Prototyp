"""Audio für den Telefonassistenten (ADR-010, J7): Sprechpausen erkennen, WAV bauen, Spracherkennung, Sprachausgabe.

Telefonaudio aus Asterisk (AudioSocket): 16 Bit signed little-endian, 8 kHz, mono, 20-ms-Pakete (320 Byte).
Spracherkennung: Mistral Voxtral (EU) je Beitrag.
Sprachausgabe: Mistral Voxtral TTS (EU, Standard) oder Piper (selbst gehostet, nur mit gewerblich freigegebener Stimme).
"""

from __future__ import annotations

import base64
import io
import json
import math
import struct
import subprocess
import wave
from array import array
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import httpx
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
    """Abtastrate umrechnen (16 Bit mono).

    Ganzzahlig nach unten (z. B. 24 kHz → 8 kHz): Mittelwert je Block, das dämpft Aliasing. Sonst lineare Interpolation.
    """
    if von == nach:
        return pcm
    quelle = array("h")
    quelle.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if not quelle:
        return b""
    if von > nach and von % nach == 0:
        n = von // nach
        spuren = [quelle[i::n] for i in range(n)]
        return array("h", [sum(block) // n for block in zip(*spuren, strict=False)]).tobytes()
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
                "PIPER_MODELL ist nicht gesetzt (Pfad zur .onnx-Stimme mit gewerblich freigegebener Lizenz)."
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


class SprachausgabeFehler(Exception):
    """Die Sprachausgabe hat kein Audio geliefert; der Anruf endet dann mit einer Notiz „Anruf ohne Nachricht“."""


def wav_lesen(daten: bytes) -> tuple[bytes, int]:
    """WAV → (16-Bit-PCM mono, Abtastrate). Versteht 16-Bit-PCM und 32-Bit-Float, bei Stereo zählt der erste Kanal."""
    if daten[:4] != b"RIFF" or daten[8:12] != b"WAVE":
        raise SprachausgabeFehler("Antwort ist keine WAV-Datei.")
    pos, fmt, roh = 12, None, None
    while pos + 8 <= len(daten):
        kennung, laenge = daten[pos : pos + 4], struct.unpack("<I", daten[pos + 4 : pos + 8])[0]
        inhalt = daten[pos + 8 : pos + 8 + laenge]
        if kennung == b"fmt ":
            fmt = inhalt
        elif kennung == b"data":
            roh = inhalt
            break
        pos += 8 + laenge + (laenge % 2)
    if fmt is None or roh is None or len(fmt) < 16:
        raise SprachausgabeFehler("WAV-Datei ohne Format- oder Datenteil.")
    art, kanaele, rate, _, _, bits = struct.unpack("<HHIIHH", fmt[:16])
    if art == 0xFFFE and len(fmt) >= 26:  # WAVE_FORMAT_EXTENSIBLE: eigentliche Art im Untertyp
        art = struct.unpack("<H", fmt[24:26])[0]
    if art == 1 and bits == 16:
        werte = array("h")
        werte.frombytes(roh[: len(roh) - len(roh) % 2])
    elif art == 3 and bits == 32:
        gleit = array("f")
        gleit.frombytes(roh[: len(roh) - len(roh) % 4])
        werte = array("h", [max(-32768, min(32767, int(x * 32767))) for x in gleit])
    else:
        raise SprachausgabeFehler(f"WAV-Format nicht unterstützt (Art {art}, {bits} Bit).")
    if kanaele > 1:
        werte = werte[::kanaele]
    return werte.tobytes(), rate


def _fester_text(text: str) -> bool:
    """Nur feste Sätze (Ansage mit Pflichthinweis, Verabschiedung, Ersatzsatz) werden im Speicher gehalten."""
    from .gespraech import ABSCHIED, ERSATZ, PFLICHTHINWEIS

    return PFLICHTHINWEIS in text or text in (ABSCHIED, ERSATZ)


class Voxtral:
    """Sprachausgabe über Mistral Voxtral TTS (EU-API, ADR-005), Standard für den Telefonassistenten.

    Endpunkt laut Mistral-Doku (gelesen 5. November 2026): POST {MISTRAL_BASIS_URL}/v1/audio/speech mit `model`,
    `input`, `voice_id` und `response_format`. Die Antwort enthält das Audio base64-kodiert in `audio_data`; Ausgabe
    24 kHz mono. Wir fordern WAV an, weil der Kopf Abtastrate und Bittiefe sicher angibt. Gegen den echten Dienst
    ist das noch nicht getestet.

    Feste Sätze (Ansage, Verabschiedung) hält der Dienst im Speicher: Sie kosten so nur einmal je Betrieb und
    kommen ohne Wartezeit. Antworten der KI werden nie zwischengespeichert.
    """

    MAX_SPEICHER = 200

    def __init__(
        self,
        modell: str | None = None,
        stimme: str | None = None,
        client: httpx.Client | None = None,
        zwischenspeichern: Callable[[str], bool] = _fester_text,
    ) -> None:
        if not settings.MISTRAL_API_KEY:
            raise ValueError("MISTRAL_API_KEY ist nicht gesetzt: ohne Schlüssel keine Sprachausgabe über Voxtral.")
        self.modell = modell or settings.MISTRAL_TTS_MODELL
        self.stimme = stimme or settings.MISTRAL_TTS_STIMME
        self.http = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0))
        self.zwischenspeichern = zwischenspeichern
        self._speicher: OrderedDict[str, bytes] = OrderedDict()

    def sprechen(self, text: str) -> bytes:
        if text in self._speicher:
            self._speicher.move_to_end(text)
            return self._speicher[text]
        pcm = self._abrufen(text)
        if self.zwischenspeichern(text):
            self._speicher[text] = pcm
            while len(self._speicher) > self.MAX_SPEICHER:
                self._speicher.popitem(last=False)
        return pcm

    def _abrufen(self, text: str) -> bytes:
        try:
            antwort = self.http.post(
                settings.MISTRAL_BASIS_URL.rstrip("/") + "/v1/audio/speech",
                headers={"Authorization": f"Bearer {settings.MISTRAL_API_KEY}"},
                json={"model": self.modell, "input": text, "voice_id": self.stimme, "response_format": "wav"},
            )
        except httpx.TransportError as fehler:
            raise SprachausgabeFehler("Die Sprachausgabe ist nicht erreichbar.") from fehler
        if antwort.status_code >= 400:
            raise SprachausgabeFehler(f"Die Sprachausgabe wurde abgelehnt (HTTP {antwort.status_code}).")
        if antwort.headers.get("content-type", "").startswith("application/json"):
            try:
                audio = base64.b64decode(str(antwort.json()["audio_data"]))
            except (KeyError, ValueError) as fehler:
                raise SprachausgabeFehler("Antwort der Sprachausgabe ohne Audio.") from fehler
        else:
            audio = antwort.content
        pcm, rate = wav_lesen(audio)
        return umrechnen(pcm, rate)


def sprachausgabe(art: str | None = None) -> Sprachausgabe:
    """Sprachausgabe laut Einstellung TELEFON_SPRACHAUSGABE: „voxtral“ (Standard) oder „piper“."""
    art = (art or settings.TELEFON_SPRACHAUSGABE).lower()
    if art == "voxtral":
        return Voxtral()
    if art == "piper":
        return Piper()
    raise ValueError(f"Unbekannte Sprachausgabe „{art}“ (erlaubt: voxtral, piper).")


class Stille:
    """Ersatz-Sprachausgabe für Tests und Trockenläufe: Stille, etwa so lang wie gesprochen."""

    def sprechen(self, text: str) -> bytes:
        return bytes(RAHMEN_BYTES * max(1, len(text) // 15))
