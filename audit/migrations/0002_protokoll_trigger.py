"""Postgres-Trigger: Protokolleinträge sind unveränderlich (F2).

UPDATE ist immer verboten. DELETE nur für Einträge, die älter als 8 Jahre sind (Löschfrist
laut Sicherheit-Datenschutz-Betrieb.md). Damit kann auch ein Fehler in der App oder ein
direkter SQL-Zugriff mit App-Rechten das Protokoll nicht verändern.
"""

from django.db import migrations

ANLEGEN = """
CREATE OR REPLACE FUNCTION audit_protokoll_schuetzen() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'Protokolleintraege sind unveraenderlich (UPDATE verboten)';
    END IF;
    IF TG_OP = 'DELETE' THEN
        IF OLD.zeit < now() - interval '8 years' THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'Protokolleintraege duerfen erst nach 8 Jahren geloescht werden';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_protokoll_schutz
BEFORE UPDATE OR DELETE ON audit_protokolleintrag
FOR EACH ROW EXECUTE FUNCTION audit_protokoll_schuetzen();
"""

ENTFERNEN = """
DROP TRIGGER IF EXISTS audit_protokoll_schutz ON audit_protokolleintrag;
DROP FUNCTION IF EXISTS audit_protokoll_schuetzen();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [migrations.RunSQL(ANLEGEN, ENTFERNEN)]
