"""Führt die KI-Testfälle gegen das echte Modell aus (Bedrock eu-central-1, EU-Profil).

Voraussetzungen (Umgebungsvariablen): AWS-Zugang für Bedrock (z. B. AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY oder
AWS_PROFILE), BEDROCK_REGION, BEDROCK_MODELL. Kosten: je Fall ein Aufruf; Obergrenze über --max-faelle.
Die Daten der Fälle sind erfunden; es werden keine echten Kundendaten gesendet.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.test import override_settings

from capture.ki_testfaelle import abnahme, ausfuehren, faelle_laden


class Command(BaseCommand):
    help = "Ruft das echte KI-Modell mit den Testfällen aus tests/ki_faelle auf und vergleicht die Ergebnisse."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--nur", default="", help="Nur Fälle, deren Name diesen Text enthält")
        parser.add_argument("--max-faelle", type=int, default=20, help="Kostenbremse: höchstens so viele Fälle")

    def handle(self, *args: Any, **optionen: Any) -> None:
        import tempfile

        faelle = [f for f in faelle_laden() if optionen["nur"] in f.name][: optionen["max_faelle"]]
        if not faelle:
            raise CommandError("Keine Testfälle gefunden.")
        ergebnisse = []
        with tempfile.TemporaryDirectory() as ablage, override_settings(DATEIABLAGE=ablage):
            for fall in faelle:
                ergebnis = ausfuehren(fall)
                ergebnisse.append(ergebnis)
                zeichen = "OK  " if ergebnis.bestanden else "FAIL"
                self.stdout.write(f"{zeichen} {fall.name}{' (Sicherheit)' if fall.sicherheit else ''}")
                for zeile in ([ergebnis.fehler] if ergebnis.fehler else []) + ergebnis.abweichungen:
                    self.stdout.write(f"     - {zeile}")
        ok, text = abnahme(ergebnisse)
        self.stdout.write(text)
        if not ok:
            raise CommandError(f"Abnahme nicht erreicht: {text}")
