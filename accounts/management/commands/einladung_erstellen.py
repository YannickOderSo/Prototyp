from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from accounts.services import einladung_erstellen


class Command(BaseCommand):
    help = "Erzeugt Einladungscodes für die geschlossene Beta. Codes werden nur hier im Klartext angezeigt."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--anzahl", type=int, default=1)
        parser.add_argument("--notiz", default="")
        parser.add_argument("--tage", type=int, default=30, help="Gültigkeit in Tagen (0 = unbegrenzt)")

    def handle(self, *args: Any, **optionen: Any) -> None:
        for _ in range(optionen["anzahl"]):
            code = einladung_erstellen(notiz=optionen["notiz"], gueltig_tage=optionen["tage"] or None)
            self.stdout.write(code)
