"""M4-05: Sicherung mit restic, Restore-Probe und Wiederherstellung gegen echtes Postgres (restic nachgebaut)."""

import http.server
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from django.db import connection

SKRIPTE = Path(__file__).resolve().parents[2] / "docker" / "backup"
FAKE = Path(__file__).resolve().parent / "fake_restic.py"
WERKZEUGE = ("bash", "pg_dump", "pg_restore", "psql", "createdb", "dropdb", "jq")

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(any(shutil.which(w) is None for w in WERKZEUGE), reason="Postgres-Werkzeuge fehlen"),
]


@pytest.fixture
def umgebung(tmp_path):
    bin_ordner = tmp_path / "bin"
    bin_ordner.mkdir()
    restic = bin_ordner / "restic"
    restic.write_text(f'#!/bin/sh\nexec {sys.executable} {FAKE} "$@"\n')
    restic.chmod(0o755)
    s = connection.settings_dict
    return {
        "PATH": f"{bin_ordner}:{os.environ['PATH']}",
        "FAKE_RESTIC_DIR": str(tmp_path / "repo"),
        "RESTIC_REPOSITORY": "sftp:u1@u1.your-storagebox.de:/cockpit",
        "RESTIC_PASSWORD": "nur-test",
        "PGHOST": s["HOST"] or "localhost",
        "PGPORT": str(s["PORT"] or 5432),
        "PGUSER": s["USER"],
        "PGPASSWORD": s["PASSWORD"],
        "PGDATABASE": s["NAME"],
        "PROBE_DB": f"{s['NAME']}_probe",
        "HOME": str(tmp_path),
    }


def _lauf(skript, umgebung, *argumente):
    return subprocess.run(
        ["bash", str(SKRIPTE / skript), *argumente], env=umgebung, capture_output=True, text=True, timeout=120
    )


def _datenbanken(umgebung):
    ergebnis = subprocess.run(
        ["psql", "--dbname", "postgres", "-Atqc", "SELECT datname FROM pg_database"],
        env=umgebung,
        capture_output=True,
        text=True,
        check=True,
    )
    return set(ergebnis.stdout.split())


class _Ping(http.server.BaseHTTPRequestHandler):
    pfade: list[str] = []

    def do_GET(self):
        _Ping.pfade.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def ping():
    _Ping.pfade = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _Ping)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/ping", _Ping.pfade
    server.shutdown()


def test_sicherung_speichert_dump_und_wendet_aufbewahrung_an(umgebung, ping):
    url, pfade = ping
    ergebnis = _lauf("sicherung.sh", {**umgebung, "BACKUP_PING_URL": url, "BACKUP_PRUEFEN": "1"})
    assert ergebnis.returncode == 0, ergebnis.stderr
    repo = Path(umgebung["FAKE_RESTIC_DIR"])
    aufrufe = (repo / "aufrufe.log").read_text()
    assert "--tag cockpit-db" in aufrufe and "pg_dump --format=custom --no-owner --no-privileges" in aufrufe
    assert "forget --tag cockpit-db --host cockpit --keep-daily 30 --keep-monthly 12 --prune" in aufrufe
    assert "\ncheck\n" in aufrufe
    dumps = [p for p in repo.iterdir() if p.name not in {"index.json", "aufrufe.log"}]
    assert len(dumps) == 1 and dumps[0].read_bytes().startswith(b"PGDMP")
    assert pfade == ["/ping"]


def test_sicherung_fehlgeschlagen_kein_snapshot_und_fail_ping(umgebung, ping):
    url, pfade = ping
    ergebnis = _lauf("sicherung.sh", {**umgebung, "PGDATABASE": "gibt_es_nicht", "BACKUP_PING_URL": url})
    assert ergebnis.returncode != 0
    assert not (Path(umgebung["FAKE_RESTIC_DIR"]) / "index.json").exists()
    assert "forget" not in (Path(umgebung["FAKE_RESTIC_DIR"]) / "aufrufe.log").read_text()
    assert pfade == ["/ping/fail"]


def test_restore_probe_ok_und_raeumt_auf(umgebung):
    assert _lauf("sicherung.sh", umgebung).returncode == 0
    ergebnis = _lauf("restore_probe.sh", umgebung)
    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Restore-Probe OK" in ergebnis.stdout
    assert umgebung["PROBE_DB"] not in _datenbanken(umgebung)


def test_restore_probe_meldet_zu_alte_sicherung(umgebung):
    assert _lauf("sicherung.sh", {**umgebung, "FAKE_RESTIC_ALTER_STUNDEN": "30"}).returncode == 0
    ergebnis = _lauf("restore_probe.sh", umgebung)
    assert ergebnis.returncode == 1
    assert "30 Stunden alt" in ergebnis.stderr


def test_restore_probe_ohne_sicherung(umgebung):
    ergebnis = _lauf("restore_probe.sh", umgebung)
    assert ergebnis.returncode == 1 and "keine Sicherung" in ergebnis.stderr


def test_wiederherstellen_braucht_bestaetigung(umgebung):
    assert _lauf("wiederherstellen.sh", umgebung, "latest").returncode == 2


def test_wiederherstellen_tauscht_datenbank(umgebung):
    """Gegen eine eigene Wegwerf-Datenbank, damit die Test-Datenbank unberührt bleibt."""
    assert _lauf("sicherung.sh", umgebung).returncode == 0
    ziel = f"{umgebung['PGDATABASE']}_wh"
    env = {**umgebung, "PGDATABASE": ziel}
    vorher = _datenbanken(umgebung)
    subprocess.run(["createdb", ziel], env=umgebung, check=True)
    try:
        ergebnis = _lauf("wiederherstellen.sh", env, "latest", "--ich-habe-web-und-worker-gestoppt")
        assert ergebnis.returncode == 0, ergebnis.stderr
        migrationen = subprocess.run(
            ["psql", "--dbname", ziel, "-Atqc", "SELECT count(*) FROM django_migrations"],
            env=umgebung,
            capture_output=True,
            text=True,
            check=True,
        )
        assert int(migrationen.stdout) > 10
        neu = _datenbanken(umgebung) - vorher
        assert ziel in neu and any(d.startswith(f"{ziel}_vor_wiederherstellung_") for d in neu)
    finally:
        for name in _datenbanken(umgebung) - vorher:
            subprocess.run(["dropdb", "--if-exists", name], env=umgebung, check=False)
