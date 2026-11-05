from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from accounts.models import Firma
from audit.services import protokolliere
from reports.export import zip_export


class Command(BaseCommand):
    help = (
        "Exportiert alle Vorschläge, Versände, Erfassungen und das Protokoll einer Firma als ZIP (Betroffenenrechte)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("firma_id", type=int)
        parser.add_argument("ziel", type=Path)

    def handle(self, *args: Any, **optionen: Any) -> None:
        firma = Firma.objects.filter(pk=optionen["firma_id"]).first()
        if firma is None:
            raise CommandError("Firma nicht gefunden")
        inhalt = zip_export(firma)
        optionen["ziel"].write_bytes(inhalt)
        protokolliere(firma, "export.erstellt", objekt=firma, daten={"bytes": len(inhalt), "per": "kommando"})
        self.stdout.write(f"{len(inhalt)} Bytes nach {optionen['ziel']} geschrieben")
