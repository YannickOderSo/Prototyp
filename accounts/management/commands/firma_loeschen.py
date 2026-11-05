from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from accounts.models import Firma
from audit.loeschfristen import firma_loeschen


class Command(BaseCommand):
    help = (
        "Löscht alle fachlichen Daten einer Firma (Betroffenenrechte). Das Protokoll bleibt 8 Jahre als Nachweis. "
        "Vorher mit firma_export sichern."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("firma_id", type=int)
        parser.add_argument("--bestaetigen", required=True, help="Zur Sicherheit den genauen Firmennamen wiederholen")

    def handle(self, *args: Any, **optionen: Any) -> None:
        firma = Firma.objects.filter(pk=optionen["firma_id"]).first()
        if firma is None:
            raise CommandError("Firma nicht gefunden")
        if optionen["bestaetigen"] != firma.name:
            raise CommandError(f"Bestätigung passt nicht. Erwartet wird der Firmenname „{firma.name}“.")
        anzahlen = firma_loeschen(firma)
        for name, anzahl in anzahlen.items():
            self.stdout.write(f"{name}: {anzahl}")
        self.stdout.write("Firma gelöscht. Das Protokoll bleibt erhalten.")
