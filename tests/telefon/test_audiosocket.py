"""M8-05: AudioSocket-Dienst mit simuliertem Asterisk, Sprechpausen, Audio-Hilfen und Piper-Anbindung (J7)."""

import asyncio
import json
import struct
import sys
import wave
from array import array
from io import BytesIO

import pytest

from telefon import gespraech as fuehrung
from telefon.audiosocket import ART_AUDIO, ART_ENDE, ART_UUID, dienst, lesen, nachricht
from telefon.models import Gespraech, Rueckruf
from telefon.sprache import RAHMEN_BYTES, Piper, Sprechpausen, Stille, als_wav, pegel, umrechnen
from tests.ki_fake import antwort

LAUT = array("h", [3000 if i % 2 else -3000 for i in range(160)]).tobytes()
LEISE = bytes(RAHMEN_BYTES)


def _ki_antwort(text, beenden=False, **erfasst):
    felder = {"name": "", "anliegen": "", "rueckrufnummer": "", "beste_zeit": "", "dringlichkeit": ""}
    felder.update(erfasst)
    return antwort({"antwort": text, "erfasst": felder, "beenden": beenden})


def test_audio_hilfen():
    assert pegel(LAUT) == pytest.approx(3000) and pegel(LEISE) == 0
    with wave.open(BytesIO(als_wav(LAUT * 50))) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (8000, 1, 2, 8000)
    assert len(umrechnen(bytes(2 * 22050), 22050)) == 2 * 8000
    assert umrechnen(LAUT, 8000) == LAUT


def test_sprechpausen():
    p = Sprechpausen()
    assert all(p.rahmen(LEISE) is None for _ in range(30))  # nur Stille: kein Beitrag
    assert all(p.rahmen(LAUT) is None for _ in range(20))
    beitrag = None
    for _ in range(40):
        beitrag = p.rahmen(LEISE) or beitrag
    # 3 stille Vorlauf-Rahmen + 20 laute + 40 stille bis zum Ende des Beitrags
    assert beitrag is not None and len(beitrag) == RAHMEN_BYTES * (3 + 20 + 40)


def test_piper_mit_ersatzprogramm(tmp_path):
    programm = tmp_path / "piper"
    programm.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdin.read()\nsys.stdout.buffer.write(bytes(2 * 16000))\n"
    )
    programm.chmod(0o755)
    modell = tmp_path / "stimme.onnx"
    (tmp_path / "stimme.onnx.json").write_text(json.dumps({"audio": {"sample_rate": 16000}}))
    assert len(Piper(befehl=str(programm), modell=str(modell)).sprechen("Guten Tag")) == 2 * 8000
    with pytest.raises(ValueError, match="PIPER_MODELL"):
        Piper(befehl=str(programm), modell="")


async def _bis_ruhe(reader, ruhe=0.3):
    """Liest Nachrichten, bis der Dienst `ruhe` Sekunden schweigt. Gibt (Audio-Rahmen, Ende gesehen) zurück."""
    rahmen, ende = 0, False
    while True:
        try:
            m = await asyncio.wait_for(lesen(reader), timeout=ruhe)
        except TimeoutError:
            return rahmen, ende
        if m is None:
            return rahmen, True
        if m[0] == ART_AUDIO:
            rahmen += 1
        if m[0] == ART_ENDE:
            return rahmen, True


async def _sprechen(writer, laute=20, stille=50):
    for r in [LAUT] * laute + [LEISE] * stille:
        writer.write(nachricht(ART_AUDIO, r))
    await writer.drain()


def _szenario(uuid_bytes, ablauf):
    async def lauf():
        server = await dienst("127.0.0.1", 0, Stille(), spracherkennung=ablauf["stt"], takt=0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(nachricht(ART_UUID, uuid_bytes))
        await writer.drain()
        ergebnis = await ablauf["client"](reader, writer)
        writer.close()
        server.close()
        await server.wait_closed()
        return ergebnis

    return asyncio.run(lauf())


@pytest.mark.django_db(transaction=True)
def test_anruf_ueber_audiosocket_ergibt_rueckruf(firma, ki):
    ki(
        _ki_antwort(
            "Danke, Herr Weber. Passt die Nummer, von der Sie anrufen?", name="Herr Weber", anliegen="Wasserfleck"
        ),
        _ki_antwort("Notiert.", beenden=True, dringlichkeit="dringend"),
    )
    gesagt = iter(["Hallo, hier Weber, wir haben einen Wasserfleck.", "Ja, die passt."])
    g, _ = fuehrung.starten(firma, anrufer_nummer="0151 2345678", angerufene_nummer="+4930111")

    async def client(reader, writer):
        ansage, _ = await _bis_ruhe(reader)
        await _sprechen(writer)
        antwort1, ende1 = await _bis_ruhe(reader, ruhe=1.0)
        await _sprechen(writer)
        antwort2, ende2 = await _bis_ruhe(reader, ruhe=2.0)
        return ansage, antwort1, ende1, antwort2, ende2

    ansage, antwort1, ende1, antwort2, ende2 = _szenario(
        g.uuid.bytes, {"stt": lambda pcm: next(gesagt), "client": client}
    )
    assert ansage > 0 and antwort1 > 0 and not ende1
    assert antwort2 > 0 and ende2  # Verabschiedung, dann legt der Dienst auf
    r = Rueckruf.objects.get(gespraech=g)
    assert (r.name, r.anliegen, r.dringlichkeit, r.rueckrufnummer) == (
        "Herr Weber",
        "Wasserfleck",
        "dringend",
        "01512345678",
    )
    g.refresh_from_db()
    assert g.status == "beendet" and g.verlauf[-1]["text"].endswith(fuehrung.ABSCHIED)


@pytest.mark.django_db(transaction=True)
def test_aufgelegt_nach_der_ansage(firma):
    g, _ = fuehrung.starten(firma, anrufer_nummer="030 999")

    async def client(reader, writer):
        await _bis_ruhe(reader)
        writer.write(nachricht(ART_ENDE))
        await writer.drain()
        await asyncio.sleep(0.3)

    _szenario(g.uuid.bytes, {"stt": lambda pcm: "", "client": client})
    g.refresh_from_db()
    assert g.status == "abgebrochen"
    assert Rueckruf.objects.get(gespraech=g).anliegen.startswith("Anruf ohne Nachricht")


@pytest.mark.django_db(transaction=True)
def test_unbekannte_uuid_wird_aufgelegt(firma):
    async def client(reader, writer):
        return await lesen(reader)

    erste = _szenario(bytes(16), {"stt": lambda pcm: "", "client": client})
    assert erste == (ART_ENDE, b"")
    assert not Gespraech.objects.exists()


def test_nachrichtenformat():
    assert nachricht(ART_UUID, b"x" * 16)[:3] == struct.pack(">BH", 0x01, 16)
    assert nachricht(ART_ENDE) == b"\x00\x00\x00"
