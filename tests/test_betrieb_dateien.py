"""M0-02: Container laufen ohne Root, Compose enthält web, worker, db; die DB ist nicht öffentlich."""

from pathlib import Path

import yaml

WURZEL = Path(__file__).resolve().parent.parent


def test_dockerfile_laeuft_ohne_root():
    zeilen = (WURZEL / "Dockerfile").read_text().splitlines()
    user_zeilen = [z for z in zeilen if z.startswith("USER ")]
    assert user_zeilen, "Dockerfile setzt keinen USER"
    assert user_zeilen[-1].split()[1].split(":")[0] not in {"root", "0"}


def test_dockerfile_nutzt_lockfile():
    text = (WURZEL / "Dockerfile").read_text()
    assert "uv sync --frozen" in text
    assert "python:3.12" in text


def test_compose_lokal_hat_web_worker_db():
    compose = yaml.safe_load((WURZEL / "docker-compose.yml").read_text())
    dienste = compose["services"]
    assert {"web", "worker", "db"} <= set(dienste)
    assert dienste["worker"]["command"] == ["worker"]
    assert dienste["db"]["image"].startswith("postgres:16")
    # lokale Ports nur auf 127.0.0.1
    for name, dienst in dienste.items():
        for port in dienst.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), (name, port)


def test_makefile_hat_dev_und_test():
    text = (WURZEL / "Makefile").read_text()
    assert "\ndev:" in text
    assert "\ntest:" in text


def test_keine_env_datei_im_repo():
    import subprocess

    dateien = subprocess.run(["git", "ls-files"], cwd=WURZEL, capture_output=True, text=True, check=True).stdout
    assert not any(z == ".env" for z in dateien.splitlines())


def test_telefon_dienste_nur_mit_profil_und_ohne_offene_ports():
    """p3-compose-telefon: Asterisk und AudioSocket-Dienst starten nur mit Profil „telefon“; AudioSocket nur lokal."""
    compose = yaml.safe_load((WURZEL / "docker-compose.prod.yml").read_text())
    dienste = compose["services"]
    assert dienste["telefon"]["profiles"] == ["telefon"] and dienste["asterisk"]["profiles"] == ["telefon"]
    assert dienste["telefon"]["command"][:3] == ["python", "manage.py", "telefon_dienst"]
    assert dienste["telefon"]["ports"] == ["127.0.0.1:9092:9092"]
    assert dienste["asterisk"]["network_mode"] == "host"
    # Zugangsdaten nur vom Server, schreibgeschützt eingebunden
    assert all(str(v).endswith(":ro") for v in dienste["asterisk"]["volumes"])
    # Datenbank bleibt ohne öffentlichen Port, auch mit Telefon
    assert "ports" not in dienste["db"]


def test_asterisk_image_ohne_offene_verwaltung():
    datei = (WURZEL / "docker" / "asterisk" / "Dockerfile").read_text()
    module = (WURZEL / "docker" / "asterisk" / "modules.conf").read_text()
    assert "USER asterisk" in datei
    assert "manager.conf" in datei and "http.conf" in datei  # entfernt: AMI und HTTP-Server bleiben aus
    for modul in ("chan_sip.so", "chan_iax2.so", "res_ari.so"):
        assert f"noload => {modul}" in module


def test_systemcheck_kennungen_eindeutig():
    """Jede Kennung `cockpit.E…`/`W…` gibt es nur einmal (E004 war doppelt vergeben, korrigiert am 7.11.2026)."""
    import re

    kennungen: list[str] = []
    for datei in WURZEL.glob("*/checks.py"):
        kennungen += re.findall(r'id="(cockpit\.[EW]\d{3})"', datei.read_text())
    assert kennungen and len(kennungen) == len(set(kennungen)), sorted(kennungen)
