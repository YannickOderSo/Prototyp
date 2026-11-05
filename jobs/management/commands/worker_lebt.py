"""Docker-Healthcheck des Worker-Containers: Exit 0, wenn ein Lebenszeichen jünger als 2 Minuten ist."""

import sys
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from jobs.models import Job, WorkerLebenszeichen


class Command(BaseCommand):
    help = "Prüft das Lebenszeichen des Workers (für den Docker-Healthcheck)."

    def handle(self, *args: Any, **optionen: Any) -> None:
        jetzt = timezone.now()
        lebt = WorkerLebenszeichen.objects.filter(zuletzt__gte=jetzt - timedelta(minutes=2)).exists()
        lebt = lebt or Job.objects.filter(status=Job.Status.LAEUFT, gesperrt_bis__gt=jetzt).exists()
        if not lebt:
            self.stderr.write("Kein Lebenszeichen des Workers in den letzten 2 Minuten")
            sys.exit(1)
        self.stdout.write("Worker lebt")
