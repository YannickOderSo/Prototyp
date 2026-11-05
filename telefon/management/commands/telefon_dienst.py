"""Startet den AudioSocket-Dienst für Asterisk (ADR-010). Läuft als eigener Prozess neben web und worker."""

import asyncio
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from telefon.audiosocket import dienst
from telefon.sprache import Piper, Sprachausgabe, Stille


class Command(BaseCommand):
    help = "AudioSocket-Dienst des KI-Telefonassistenten (Asterisk verbindet sich hierher)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--host", default=settings.TELEFON_AUDIOSOCKET_HOST)
        parser.add_argument("--port", type=int, default=settings.TELEFON_AUDIOSOCKET_PORT)
        parser.add_argument("--stumm", action="store_true", help="Ohne Sprachausgabe (nur für Trockenläufe)")

    def handle(self, *args: Any, **optionen: Any) -> None:
        if not settings.TELEFON_ASTERISK_TOKEN:
            raise CommandError("TELEFON_ASTERISK_TOKEN fehlt: ohne Geheimnis nimmt Belegfluss keine Anrufe an.")
        tts: Sprachausgabe
        if optionen["stumm"]:
            tts = Stille()
        else:
            try:
                tts = Piper()
            except ValueError as fehler:
                raise CommandError(str(fehler)) from fehler

        async def laufen() -> None:
            server = await dienst(optionen["host"], optionen["port"], tts)
            self.stdout.write(f"Telefonassistent hört auf {optionen['host']}:{optionen['port']} (AudioSocket)")
            async with server:
                await server.serve_forever()

        asyncio.run(laufen())
