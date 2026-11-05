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
