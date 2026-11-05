"""Startwerte der Basiszins-Tabelle (Mahnlogik-und-Recht.md). Vor Go-live mit der Bundesbank abgleichen."""

from datetime import date
from decimal import Decimal

from django.db import migrations

STARTWERTE = [
    (date(2025, 1, 1), Decimal("2.2700")),
    (date(2025, 7, 1), Decimal("1.2700")),
    (date(2026, 1, 1), Decimal("1.2700")),
    (date(2026, 7, 1), Decimal("1.5200")),
]


def anlegen(apps, schema_editor):
    Basiszins = apps.get_model("dunning", "Basiszins")
    for gueltig_ab, satz in STARTWERTE:
        Basiszins.objects.get_or_create(
            gueltig_ab=gueltig_ab,
            defaults={"satz": satz, "quelle": "Startwert laut Vault; Bundesbank-Pressemitteilung vom 30.06.2026"},
        )


def entfernen(apps, schema_editor):
    Basiszins = apps.get_model("dunning", "Basiszins")
    Basiszins.objects.filter(gueltig_ab__in=[d for d, _ in STARTWERTE]).delete()


class Migration(migrations.Migration):
    dependencies = [("dunning", "0001_initial")]

    operations = [migrations.RunPython(anlegen, entfernen)]
