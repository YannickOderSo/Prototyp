from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from jobs.worker import Worker


class Command(BaseCommand):
    help = "Startet den Worker der Job-Queue (beendet sich sauber bei SIGTERM)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--name", default=None, help="Name des Workers (Standard: Rechner-PID)")
        parser.add_argument("--sperrzeit", type=int, default=300, help="Sekunden bis ein Job als hängend gilt")
        parser.add_argument("--bis-leer", action="store_true", help="Nur fällige Jobs abarbeiten und dann beenden")

    def handle(self, *args: Any, **optionen: Any) -> None:
        worker = Worker(name=optionen["name"], sperrzeit=optionen["sperrzeit"])
        worker.signale_einrichten()
        self.stdout.write(f"Worker {worker.name} gestartet")
        worker.schleife(bis_leer=optionen["bis_leer"])
        self.stdout.write(f"Worker {worker.name} beendet")
