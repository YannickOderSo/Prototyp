"""M0-06: Basis-Layout mit HTMX, mobil zuerst, Fuß mit Rechtstexten (F5), CSP ohne Inline-Skripte."""

import re

import pytest
from django.urls import reverse

from web.rechtstexte import RECHTSTEXTE


@pytest.fixture
def startseite(client, db):
    return client.get(reverse("accounts:login"))


def test_layout_laedt_htmx_lokal_und_viewport(startseite):
    html = startseite.content.decode()
    assert startseite.status_code == 200
    assert '<html lang="de">' in html
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in html
    assert re.search(r'<script src="/static/web/htmx-[\d.]+\.min\.js" defer></script>', html)
    assert "X-CSRFToken" in html


def test_keine_inline_skripte_oder_styles(startseite):
    html = startseite.content.decode()
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "Inline-Skript gefunden"
    assert "<style" not in html
    assert 'style="' not in html


def test_sicherheitsheader(startseite):
    csp = startseite.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert startseite.headers["X-Frame-Options"] == "DENY"
    assert startseite.headers["X-Content-Type-Options"] == "nosniff"


def test_fuss_verlinkt_alle_rechtstexte(startseite):
    html = startseite.content.decode()
    for text in RECHTSTEXTE:
        assert reverse("web:rechtstext", args=[text.slug]) in html
        assert text.titel in html


@pytest.mark.parametrize("slug", [t.slug for t in RECHTSTEXTE])
def test_rechtstexte_sind_erreichbar_und_als_platzhalter_markiert(client, db, slug):
    antwort = client.get(reverse("web:rechtstext", args=[slug]))
    assert antwort.status_code == 200
    assert "Platzhalter" in antwort.content.decode()


def test_unbekannter_rechtstext_404(client, db):
    assert client.get("/rechtliches/gibtsnicht/").status_code == 404


def test_css_ist_mobil_zuerst():
    from pathlib import Path

    css = (Path(__file__).resolve().parents[2] / "web" / "static" / "web" / "style.css").read_text()
    # Grundregeln ohne Media-Query, Erweiterung nur per min-width
    assert "@media (min-width" in css
    assert "@media (max-width" not in css
    assert "overflow-x: hidden" in css
