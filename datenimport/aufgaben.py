"""Jobs des Excel-Imports."""

from connectors.jobs import mit_connector
from jobs.models import Job
from jobs.registry import job

from .services import ausfuehren


@job("datenimport.ausfuehren")
def _ausfuehren(j: Job) -> None:
    mit_connector(j, lambda verbindung, connector: ausfuehren(verbindung, connector, int(j.payload["vorgang_id"])))
