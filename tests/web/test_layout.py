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
    assert 'name="viewport" content="width=device-width, initial-scale=1' in html
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


def test_navigation_mit_icons_und_handy_leiste(client_inhaber):
    """Desktop: Seitenleiste mit allen Punkten; Handy: höchstens vier Hauptziele und „Mehr“ (Material: 3 bis 5)."""
    html = client_inhaber.get(reverse("web:start")).content.decode()
    seitenleiste = html.split('<aside class="seitenleiste">')[1].split("</aside>")[0]
    for titel in (
        "Cockpit",
        "Angebote &amp; Rechnungen",
        "Offene Posten",
        "Kunden",
        "Mahnungen",
        "Berichte",
        "Einstellungen",
    ):
        assert f'<span class="nav-titel">{titel}</span>' in seitenleiste
    assert seitenleiste.count('<svg class="icon') >= 7 and 'aria-hidden="true"' in seitenleiste
    unterleiste = html.split('<nav class="unterleiste"')[1].split("</nav>")[0]
    haupt = unterleiste.split('<details class="mehr"')[0]
    assert haupt.count("<a href=") == 4
    mehr = unterleiste.split('<div class="mehr-menue">')[1]
    assert "Berichte" in mehr and "Einstellungen" in mehr and "Kunden" in mehr


def test_zaehler_an_der_navigation(client_inhaber, firma):
    from dunning.models import Mahnvorschlag
    from ledger.models import Beleg

    beleg = Beleg.objects.create(firma=firma, extern_id="z1", nummer="RE1", offen=10, brutto=10)
    Mahnvorschlag.objects.create(firma=firma, beleg=beleg, stufe=0)
    html = client_inhaber.get(reverse("web:start")).content.decode()
    assert '<span class="zahl" aria-label="1 offen">1</span>' in html


def test_schrift_selbst_gehostet():
    from pathlib import Path

    from django.conf import settings

    css = (Path(settings.BASE_DIR) / "web" / "static" / "web" / "style.css").read_text()
    assert 'url("fonts/inter-latin-wght-normal.woff2")' in css
    assert "googleapis" not in css and "@import" not in css
    assert (Path(settings.BASE_DIR) / "web" / "static" / "web" / "fonts" / "inter-latin-wght-normal.woff2").exists()


def test_branding_belegfluss(startseite, client_inhaber):
    """Name, Logo-Zeichen inline (eindeutige Verlaufs-IDs je Vorkommen) und Favicons."""
    for html in (startseite.content.decode(), client_inhaber.get(reverse("web:start")).content.decode()):
        assert "· Belegfluss</title>" in html
        assert 'rel="icon" href="/static/web/logo/favicon.svg"' in html
        assert 'rel="apple-touch-icon" href="/static/web/logo/apple-touch-icon.png"' in html
        assert '<span class="marke-name">Beleg<span>fluss</span></span>' in html
        assert "Forderungs-Cockpit" not in html
    html = client_inhaber.get(reverse("web:start")).content.decode()
    ids = re.findall(r'<linearGradient id="([^"]+)"', html)
    assert ids and len(ids) == len(set(ids)), ids  # Seitenleiste und Handy-Kopf: keine doppelten IDs


def test_logo_dateien_vorhanden():
    from pathlib import Path

    from django.conf import settings

    ordner = Path(settings.BASE_DIR) / "web" / "static" / "web" / "logo"
    for datei in (
        "belegfluss-zeichen.svg",
        "belegfluss-logo.svg",
        "favicon.svg",
        "favicon-32.png",
        "apple-touch-icon.png",
    ):
        assert (ordner / datei).stat().st_size > 0, datei


def test_cockpit_reiter(client_inhaber, firma):
    """I2: Reiter Überblick, Rechnungen, Angebote, Mahnungen; Mahnungen nur für Freigabeberechtigte."""
    from datetime import timedelta

    from django.utils import timezone

    from ledger.models import Beleg

    heute = timezone.localdate()
    Beleg.objects.create(
        firma=firma,
        extern_id="q1",
        art="angebot",
        nummer="AN-1",
        status="offen",
        brutto=500,
        belegdatum=heute - timedelta(days=10),
        gueltig_bis=heute + timedelta(days=3),
        kontakt_name="Bau AG",
    )
    Beleg.objects.create(
        firma=firma,
        extern_id="q2",
        art="angebot",
        nummer="AN-2",
        status="angenommen",
        brutto=800,
        belegdatum=heute - timedelta(days=20),
        kontakt_name="Huber",
    )
    html = client_inhaber.get(reverse("web:start")).content.decode()
    assert 'href="?ansicht=angebote"' in html and 'href="?ansicht=mahnungen"' in html
    angebote = client_inhaber.get(reverse("web:start") + "?ansicht=angebote").content.decode()
    assert "läuft in 3 Tagen ab" in angebote and "AN-1" in angebote
    assert "1 von 2 Angeboten" in angebote and "100 %" in angebote
    assert "Am längsten überfällig" in client_inhaber.get(reverse("web:start") + "?ansicht=rechnungen").content.decode()
    assert (
        "Wartet auf Ihre Freigabe" in client_inhaber.get(reverse("web:start") + "?ansicht=mahnungen").content.decode()
    )


def test_cockpit_reiter_mahnungen_nur_fuer_freigabeberechtigte(client_mitarbeiter):
    mitarbeiter = client_mitarbeiter.get(reverse("web:start") + "?ansicht=mahnungen").content.decode()
    assert "?ansicht=mahnungen" not in mitarbeiter and "Wartet auf Ihre Freigabe" not in mitarbeiter


def test_angebote_und_rechnungen_seite(client_inhaber, firma):
    from ledger.models import Beleg

    Beleg.objects.create(firma=firma, extern_id="q1", art="angebot", nummer="AN-9", status="offen", brutto=500)
    html = client_inhaber.get(reverse("capture:liste")).content.decode()
    assert "<h1>Angebote &amp; Rechnungen</h1>" in html and "AN-9" in html
    assert "Angebot oder Rechnung erstellen" in html
