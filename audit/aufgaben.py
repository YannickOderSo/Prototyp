"""Jobs zu Protokoll und Datenschutz."""

from jobs.models import Job
from jobs.registry import job, zeitplan

from .loeschfristen import ausfuehren


@job("audit.loeschfristen")
def _loeschfristen(j: Job) -> None:
    ausfuehren()


# 3:30 Uhr: nach dem Nachtabgleich (2 Uhr), vor dem Vorschlagslauf (5 Uhr)
zeitplan("loeschfristen", "30 3 * * *", "audit.loeschfristen")
