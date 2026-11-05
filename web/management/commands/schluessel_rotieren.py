"""Rotation der Verschlüsselungsschlüssel (COCKPIT_FERNET_KEYS), Ablauf im Betriebshandbuch.

1. Neuen Schlüssel vorne in COCKPIT_FERNET_KEYS einfügen, Web und Worker neu starten.
2. `manage.py schluessel_rotieren` verschlüsselt alle Geheimnisse mit dem neuen Schlüssel neu.
3. `manage.py schluessel_rotieren --pruefen` muss „0 mit altem Schlüssel“ melden; dann den alten Schlüssel entfernen.
"""

from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import models, transaction

from accounts.models import ZweiFaktor
from cockpit.krypto import EntschluesselungFehlgeschlagen, entschluesseln, neu_verschluesseln
from connectors.models import Verbindung
from dunning.models import SmtpZugang

FELDER: list[tuple[type[models.Model], str]] = [
    (Verbindung, "schluessel_verschluesselt"),
    (SmtpZugang, "passwort_verschluesselt"),
    (ZweiFaktor, "geheimnis_verschluesselt"),
]


class Command(BaseCommand):
    help = "Verschlüsselt alle Geheimnisse mit dem ersten Schlüssel aus COCKPIT_FERNET_KEYS neu."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--pruefen", action="store_true", help="Nur prüfen, nichts ändern")

    def handle(self, *args: Any, **optionen: Any) -> None:
        neuester = Fernet(settings.FERNET_KEYS[0].encode())
        alt = neu = 0
        with transaction.atomic():
            for modell, feld in FELDER:
                for obj in modell.objects.exclude(**{feld: ""}).select_for_update():  # type: ignore[attr-defined]
                    wert = getattr(obj, feld)
                    try:
                        entschluesseln(wert)
                    except EntschluesselungFehlgeschlagen as fehler:
                        raise CommandError(f"{modell.__name__} {obj.pk}: mit keinem Schlüssel lesbar") from fehler
                    try:
                        neuester.decrypt(wert.encode())
                        continue  # schon mit dem neuesten Schlüssel
                    except InvalidToken:
                        alt += 1
                    if not optionen["pruefen"]:
                        setattr(obj, feld, neu_verschluesseln(wert))
                        obj.save(update_fields=[feld])
                        neu += 1
        if optionen["pruefen"]:
            self.stdout.write(f"{alt} mit altem Schlüssel")
        else:
            self.stdout.write(f"{neu} Geheimnisse neu verschlüsselt")
