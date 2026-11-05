"""AudioSocket-Dienst für Asterisk (ADR-010, J7).

Ablauf je Anruf:
1. Asterisk meldet den Anruf per HTTPS an (`/telefon/asterisk/anruf/`) und bekommt die Gesprächs-UUID.
2. Asterisk verbindet sich mit diesem Dienst: `AudioSocket(<uuid>,<host>:<port>)`.
3. Der Dienst spricht die Ansage, erkennt Sprechpausen, lässt jeden Beitrag transkribieren (Voxtral), holt die Antwort
   der Gesprächsführung und spricht sie (Voxtral TTS oder Piper). Während der Assistent spricht, wird eingehendes
   Audio verworfen (kein Ins-Wort-Fallen im Prototyp).
4. Ende nach der Verabschiedung, nach 4 Minuten oder wenn der Anrufer auflegt. Audio wird nie gespeichert.

Protokoll (AudioSocket): 1 Byte Art, 2 Byte Länge (big-endian), Nutzlast.
0x00 Ende, 0x01 UUID (16 Byte), 0x03 DTMF, 0x10 Audio (16 Bit, 8 kHz, mono, little-endian), 0xff Fehler.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import uuid
from collections.abc import Callable

from asgiref.sync import sync_to_async

from . import gespraech as fuehrung
from .models import Gespraech
from .sprache import RAHMEN_BYTES, Sprachausgabe, Sprechpausen, erkennen

log = logging.getLogger(__name__)

ART_ENDE, ART_UUID, ART_DTMF, ART_AUDIO, ART_FEHLER = 0x00, 0x01, 0x03, 0x10, 0xFF
MAX_DAUER_SEKUNDEN = 240
TAKT_SEKUNDEN = 0.02


def nachricht(art: int, nutzlast: bytes = b"") -> bytes:
    return struct.pack(">BH", art, len(nutzlast)) + nutzlast


async def lesen(reader: asyncio.StreamReader) -> tuple[int, bytes] | None:
    try:
        kopf = await reader.readexactly(3)
        art, laenge = struct.unpack(">BH", kopf)
        return art, (await reader.readexactly(laenge) if laenge else b"")
    except (asyncio.IncompleteReadError, ConnectionError):
        return None


def _verbindung_schliessen() -> None:
    """Datenbankverbindung des Arbeits-Threads nach jedem Anruf freigeben (langlebiger Dienst)."""
    from django.db import connection

    connection.close()


def _gespraech(kennung: uuid.UUID) -> Gespraech | None:
    return Gespraech.objects.select_related("firma").filter(uuid=kennung, kanal=Gespraech.Kanal.TELEFON).first()


class Sitzung:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        sprachausgabe: Sprachausgabe,
        spracherkennung: Callable[[bytes], str] = erkennen,
        takt: float = TAKT_SEKUNDEN,
        max_dauer: float = MAX_DAUER_SEKUNDEN,
    ) -> None:
        self.reader, self.writer = reader, writer
        self.tts, self.stt = sprachausgabe, spracherkennung
        self.takt, self.max_dauer = takt, max_dauer
        self.spricht = False
        self.eingang: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def _empfangen(self) -> None:
        while True:
            m = await lesen(self.reader)
            if m is None or m[0] in (ART_ENDE, ART_FEHLER):
                await self.eingang.put(None)
                return
            if m[0] == ART_AUDIO and not self.spricht:
                await self.eingang.put(m[1])

    async def sprechen(self, text: str) -> None:
        if not text:
            return
        pcm = await asyncio.to_thread(self.tts.sprechen, text)
        self.spricht = True
        try:
            for i in range(0, len(pcm), RAHMEN_BYTES):
                stueck = pcm[i : i + RAHMEN_BYTES]
                self.writer.write(nachricht(ART_AUDIO, stueck.ljust(RAHMEN_BYTES, b"\x00")))
                await self.writer.drain()
                if self.takt:
                    await asyncio.sleep(self.takt)
        finally:
            self.spricht = False
            while not self.eingang.empty():  # Echo und Geräusche während der Ansage verwerfen
                if self.eingang.get_nowait() is None:
                    await self.eingang.put(None)
                    break

    async def _beenden(self) -> None:
        try:
            self.writer.write(nachricht(ART_ENDE))
            await self.writer.drain()
        except ConnectionError:
            pass
        self.writer.close()

    async def laufen(self) -> None:
        erste = await lesen(self.reader)
        if erste is None or erste[0] != ART_UUID or len(erste[1]) != 16:
            await self._beenden()
            return
        g = await sync_to_async(_gespraech)(uuid.UUID(bytes=erste[1]))
        if g is None or g.status != Gespraech.Status.LAEUFT:
            log.warning("AudioSocket: unbekanntes oder beendetes Gespräch")
            await self._beenden()
            await sync_to_async(_verbindung_schliessen)()
            return
        empfang = asyncio.create_task(self._empfangen())
        loop = asyncio.get_running_loop()
        beginn = loop.time()
        pausen = Sprechpausen()
        try:
            await self.sprechen(g.verlauf[0]["text"])
            while True:
                rest = self.max_dauer - (loop.time() - beginn)
                if rest <= 0:
                    await self.sprechen(fuehrung.ABSCHIED)
                    await sync_to_async(fuehrung.abschliessen)(g, Gespraech.Status.BEENDET)
                    break
                try:
                    rahmen = await asyncio.wait_for(self.eingang.get(), timeout=rest)
                except TimeoutError:
                    continue
                if rahmen is None:  # aufgelegt
                    await sync_to_async(fuehrung.auflegen)(g)
                    break
                beitrag = pausen.rahmen(rahmen)
                if beitrag is None:
                    continue
                text = await asyncio.to_thread(self.stt, beitrag)
                if not text.strip():
                    continue
                antwort = await sync_to_async(fuehrung.antworten)(g, text)
                await self.sprechen(antwort.text)
                if antwort.beendet:
                    break
        except Exception:
            log.exception("AudioSocket: Gespräch abgebrochen", extra={"gespraech": str(g.uuid)})
            await sync_to_async(fuehrung.auflegen)(g)
        finally:
            empfang.cancel()
            await self._beenden()
            await sync_to_async(_verbindung_schliessen)()


async def dienst(
    host: str,
    port: int,
    sprachausgabe: Sprachausgabe,
    spracherkennung: Callable[[bytes], str] = erkennen,
    takt: float = TAKT_SEKUNDEN,
) -> asyncio.Server:
    async def verbindung(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await Sitzung(reader, writer, sprachausgabe, spracherkennung, takt=takt).laufen()

    return await asyncio.start_server(verbindung, host, port)
