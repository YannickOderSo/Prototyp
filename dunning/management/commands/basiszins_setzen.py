"""Basiszins nach § 247 BGB pflegen (Betriebshandbuch: halbjährlich zum 1.1. und 1.7.).

Fehlt der Satz für das laufende Halbjahr, berechnet das Cockpit keine Zinsen (schuldnergünstig) und
/healthz meldet eine Warnung. Ein bestehender Satz wird nur mit --korrigieren geändert.
"""

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from dunning.models import Basiszins

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Trägt einen Basiszinssatz ein, z. B. basiszins_setzen 2027-01-01 1.27 --quelle 'Bundesbank, 30.12.2026'"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("gueltig_ab", help="Datum 1.1. oder 1.7. im Format JJJJ-MM-TT")
        parser.add_argument("satz", help="Satz in Prozent, z. B. 1.27 oder -0.88")
        parser.add_argument("--quelle", required=True, help="Fundstelle (Bundesbank-Mitteilung mit Datum)")
        parser.add_argument("--korrigieren", action="store_true", help="Bestehenden Satz überschreiben")

    def handle(self, *args: Any, **optionen: Any) -> None:
        try:
            gueltig_ab = date.fromisoformat(optionen["gueltig_ab"])
        except ValueError as fehler:
            raise CommandError("Datum im Format JJJJ-MM-TT angeben") from fehler
        if (gueltig_ab.month, gueltig_ab.day) not in {(1, 1), (7, 1)}:
            raise CommandError("Der Basiszins ändert sich nur zum 1. Januar und 1. Juli")
        try:
            satz = Decimal(optionen["satz"].replace(",", "."))
        except InvalidOperation as fehler:
            raise CommandError("Satz als Zahl angeben, z. B. 1.27") from fehler
        if not Decimal("-10") <= satz <= Decimal("20") or satz.as_tuple().exponent < -2:  # type: ignore[operator]
            raise CommandError("Satz unplausibel (zwischen -10 und 20, höchstens zwei Nachkommastellen)")
        vorhanden = Basiszins.objects.filter(gueltig_ab=gueltig_ab).first()
        if vorhanden and not optionen["korrigieren"]:
            raise CommandError(f"Für {gueltig_ab:%d.%m.%Y} ist bereits {vorhanden.satz} % eingetragen (--korrigieren)")
        Basiszins.objects.update_or_create(
            gueltig_ab=gueltig_ab, defaults={"satz": satz, "quelle": optionen["quelle"][:200]}
        )
        log.info("Basiszins gesetzt", extra={"gueltig_ab": gueltig_ab.isoformat(), "satz": str(satz)})
        self.stdout.write(f"Basiszins ab {gueltig_ab:%d.%m.%Y}: {satz} %")
