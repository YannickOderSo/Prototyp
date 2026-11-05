"""M8-06: Sprachausgabe über Mistral Voxtral TTS (EU) statt Piper-„thorsten“ (Lizenz ungeklärt, Offene-Fragen.md)."""

import base64
import json
import struct
from array import array

import httpx
import pytest

from telefon import gespraech as fuehrung
from telefon.sprache import Piper, SprachausgabeFehler, Voxtral, sprachausgabe, umrechnen, wav_lesen


def _wav(werte, rate=24000, art=1, bits=16, kanaele=1):
    if art == 3:
        roh = array("f", werte).tobytes()
    else:
        roh = array("h", werte).tobytes()
    block = kanaele * bits // 8
    fmt = struct.pack("<HHIIHH", art, kanaele, rate, rate * block, block, bits)
    teile = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"LIST" + struct.pack("<I", 4) + b"INFO"
    teile += b"data" + struct.pack("<I", len(roh)) + roh
    return b"RIFF" + struct.pack("<I", len(teile)) + teile


class Mistral:
    """Nachgebildeter Endpunkt POST /v1/audio/speech."""

    def __init__(self, antwort=None, status=200, als_json=True):
        self.anfragen = []
        self.antwort = antwort if antwort is not None else _wav([1200] * 2400)  # 0,1 s bei 24 kHz
        self.status, self.als_json = status, als_json

    def __call__(self, request):
        self.anfragen.append(request)
        if self.status >= 400:
            return httpx.Response(self.status, json={"message": "Fehler"})
        if self.als_json:
            return httpx.Response(200, json={"audio_data": base64.b64encode(self.antwort).decode()})
        return httpx.Response(200, content=self.antwort, headers={"content-type": "audio/wav"})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def schluessel(settings):
    settings.MISTRAL_API_KEY = "test-schluessel"
    settings.MISTRAL_BASIS_URL = "https://api.mistral.ai"
    return settings


def test_voxtral_anfrage_und_umrechnung_auf_telefonqualitaet(schluessel):
    mistral = Mistral()
    pcm = Voxtral(client=mistral.client()).sprechen("Danke, Herr Weber.")
    assert len(pcm) == 2 * 800  # 0,1 s bei 8 kHz, 16 Bit
    assert set(array("h", pcm)) == {1200}
    anfrage = mistral.anfragen[0]
    assert str(anfrage.url) == "https://api.mistral.ai/v1/audio/speech"
    assert anfrage.headers["authorization"] == "Bearer test-schluessel"
    assert json.loads(anfrage.content) == {
        "model": "voxtral-mini-tts-3-0",
        "input": "Danke, Herr Weber.",
        "voice_id": "voice_481",
        "response_format": "wav",
    }


def test_voxtral_versteht_auch_rohes_audio_und_float_wav(schluessel):
    mistral = Mistral(antwort=_wav([0.5] * 240, art=3, bits=32), als_json=False)
    pcm = Voxtral(client=mistral.client()).sprechen("Hallo")
    assert len(pcm) == 2 * 80 and set(array("h", pcm)) == {16383}


def test_nur_feste_saetze_werden_zwischengespeichert(schluessel, firma):
    mistral = Mistral()
    stimme = Voxtral(client=mistral.client())
    ansage = fuehrung.ansage(firma)
    for _ in range(3):
        stimme.sprechen(ansage)
        stimme.sprechen(fuehrung.ABSCHIED)
        stimme.sprechen("Danke, Frau Weber. Passt die Nummer?")
    texte = [json.loads(a.content)["input"] for a in mistral.anfragen]
    assert texte.count(ansage) == 1 and texte.count(fuehrung.ABSCHIED) == 1
    assert texte.count("Danke, Frau Weber. Passt die Nummer?") == 3  # KI-Antworten nie im Speicher


def test_fehler_der_sprachausgabe(schluessel):
    with pytest.raises(SprachausgabeFehler, match="HTTP 500"):
        Voxtral(client=Mistral(status=500).client()).sprechen("Hallo")
    with pytest.raises(SprachausgabeFehler, match="keine WAV"):
        Voxtral(client=Mistral(antwort=b"kein audio").client()).sprechen("Hallo")


def test_ohne_schluessel_und_auswahl(settings):
    settings.MISTRAL_API_KEY = ""
    with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
        sprachausgabe("voxtral")
    settings.PIPER_MODELL = ""
    with pytest.raises(ValueError, match="PIPER_MODELL"):
        sprachausgabe("piper")
    with pytest.raises(ValueError, match="Unbekannte"):
        sprachausgabe("elevenlabs")
    settings.MISTRAL_API_KEY = "x"
    assert isinstance(sprachausgabe(), Voxtral) and not isinstance(sprachausgabe(), Piper)


def test_wav_stereo_und_umrechnung_ganzzahlig():
    pcm, rate = wav_lesen(_wav([100, -100] * 10, rate=16000, kanaele=2))
    assert rate == 16000 and set(array("h", pcm)) == {100} and len(pcm) == 2 * 10
    assert array("h", umrechnen(array("h", [0, 300, 600, 900, 900, 900]).tobytes(), 24000)).tolist() == [300, 900]
