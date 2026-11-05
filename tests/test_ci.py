"""M0-03: CI prüft ruff, mypy, pytest mit Postgres-Service, makemigrations --check und baut das Image."""

from pathlib import Path

import yaml

CI = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def _schritte(job: dict) -> str:
    return "\n".join(str(s.get("run", "")) for s in job["steps"])


def test_ci_pruefjob():
    ci = yaml.safe_load(CI.read_text())
    job = ci["jobs"]["pruefen"]
    assert job["services"]["postgres"]["image"].startswith("postgres:16")
    assert "mailpit" in job["services"]
    befehle = _schritte(job)
    for erwartet in [
        "ruff check",
        "ruff format --check",
        "mypy connectors dunning capture",
        "makemigrations --check",
        "pytest",
        "abdeckung_pruefen.py",
    ]:
        assert erwartet in befehle, erwartet


def test_ci_baut_docker_image_und_e2e():
    ci = yaml.safe_load(CI.read_text())
    assert "docker build" in _schritte(ci["jobs"]["docker"])
    assert "e2e_starten.py" in _schritte(ci["jobs"]["e2e"])


def test_pages_nur_demo_daten_ohne_geheimnisse():
    """Die Klick-Demo auf GitHub Pages nutzt nur erfundene Demo-Daten und keine Secrets."""
    text = (CI.parent / "pages.yml").read_text()
    pages = yaml.safe_load(text)
    befehle = _schritte(pages["jobs"]["bauen"])
    assert "demo_daten" in befehle and "statische_demo" in befehle
    assert "secrets." not in text
    assert pages["jobs"]["bauen"]["env"]["DJANGO_DEBUG"] == "true"
    assert pages["permissions"] == {"contents": "read"}
