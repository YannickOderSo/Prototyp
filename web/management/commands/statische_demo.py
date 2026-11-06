"""Statische Klick-Demo (z. B. für GitHub Pages) aus den Demo-Daten.

Rendert die Seiten der Demo-Firma im Prozess (Django-Testclient, nur GET) und schreibt sie als HTML-Dateien mit
relativen Links. Es gibt kein Backend: Formulare und Knöpfe zeigen nur einen Hinweis, es wird nichts gespeichert,
freigegeben oder versendet. Nur mit DJANGO_DEBUG=true und nur für die Demo-Firma aus `demo_daten`
(erfundene Daten, keine echten Personen).
"""

from __future__ import annotations

import posixpath
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.test import Client

from accounts.anmeldung import FIRMA, ZWEITER_FAKTOR_OK
from accounts.models import Firma, Nutzer

from .demo_daten import EMAIL
from .demo_daten import FIRMA as DEMO_FIRMA

START = [
    "/",
    "/posten/",
    "/posten/kunden/",
    "/mahnungen/",
    "/mahnungen/mahnplan/",
    "/erfassen/",
    "/berichte/",
    "/einstellungen/",
    "/einrichtung/",
    "/import/",
]
# Nicht in die Demo: Anmeldung, Webhooks, Downloads mit Kundendaten und Seiten mit Geheimnissen
AUSGESCHLOSSEN = (
    "/konto/",
    "/hooks/",
    "/healthz",
    "/einstellungen/verbindung/",
    "/mahnungen/smtp/",
    "/telefon/test/",  # Testanruf braucht das Backend
    "/telefon/asterisk/",
)
TROTZDEM = ("/konto/profil/", "/konto/team/")  # unbedenklich, zeigen Avatare und Team
# Reiter und Zeiträume sind Links mit Parametern; nur diese werden als eigene Seiten abgelegt
ERLAUBTE_PARAMETER = {"ansicht", "zeitraum"}
ERLAUBTE_DATEIEN = (".csv", ".xlsx")
MAX_SEITEN = 400
STATIC = "/" + settings.STATIC_URL.strip("/") + "/"

LINK = re.compile(r'(?P<attr>\b(?:href|src|action|hx-get))="(?P<url>[/?][^"]*)"')

BANNER = (
    '<div class="demo-banner" role="note"><strong>Klick-Demo</strong> mit erfundenen Daten: '
    "Nichts wird gespeichert oder versendet.</div>"
    '<div class="demo-hinweis" id="demo-hinweis" role="status" hidden></div>'
)
DEMO_CSS = """
.demo-banner { background: #101828; color: #d0d5dd; padding: 7px 16px; font-size: .8125rem; line-height: 1.4;
  text-align: center; letter-spacing: .005em; }
.demo-banner strong { display: inline-block; margin-right: 8px; padding: 1px 8px; border-radius: 999px;
  background: #fedf89; color: #4e3200; font-size: .6875rem; font-weight: 700; letter-spacing: .06em;
  text-transform: uppercase; vertical-align: 1px; }
.demo-hinweis { position: fixed; left: 16px; right: 16px; bottom: 16px; max-width: 560px; margin: 0 auto;
  background: #1f2937; color: #fff; padding: 12px 16px; border-radius: 10px; z-index: 50;
  box-shadow: 0 4px 16px rgba(0,0,0,.25); font-size: .95rem; }
"""
DEMO_JS = """// Klick-Demo: Formulare und Knöpfe zeigen nur einen Hinweis, es gibt kein Backend.
(function () {
  var hinweis = document.getElementById("demo-hinweis");
  var zeit;
  function zeigen(text) {
    if (!hinweis) return;
    hinweis.textContent = text;
    hinweis.hidden = false;
    clearTimeout(zeit);
    zeit = setTimeout(function () { hinweis.hidden = true; }, 4500);
  }
  document.addEventListener("submit", function (e) {
    e.preventDefault();
    var post = (e.target.getAttribute("method") || "get").toLowerCase() === "post";
    zeigen(post
      ? "Nur Demo: In der echten App würde das jetzt gespeichert, mit Freigabe und Protokoll."
      : "Nur Demo: Filter und Suche funktionieren in der echten App.");
  }, true);
  document.addEventListener("click", function (e) {
    var ziel = e.target.closest("[data-demo-href]");
    if (ziel) { e.preventDefault(); window.location.href = ziel.getAttribute("data-demo-href"); return; }
    var aus = e.target.closest("[data-demo-aus]");
    if (aus) { e.preventDefault(); zeigen("Nur Demo: Diese Seite gibt es nur in der echten App."); }
  }, true);
})();
"""


def _schluessel(url: str, seite: str = "/") -> str | None:
    """Normalisierte Seiten-Adresse: Pfad, bei erlaubten Parametern mit Query. None: nicht in die Demo."""
    teile = urlsplit(url)
    pfad = teile.path or urlsplit(seite).path
    if not teile.query:
        return pfad
    paare = [p.split("=", 1) for p in teile.query.split("&") if p]
    if not paare or any(len(p) != 2 or p[0] not in ERLAUBTE_PARAMETER for p in paare):
        return None
    return pfad + "?" + "&".join(f"{k}={v}" for k, v in sorted(paare))


def _datei(pfad: str) -> str:
    """Seiten-Adresse → Dateipfad: "/posten/" → "posten/index.html", "/?ansicht=x" → "index-ansicht-x.html"."""
    pfad, _, query = pfad.split("#", 1)[0].partition("?")
    zusatz = "".join(
        f"-{re.sub(r'[^a-z0-9]', '', k)}-{re.sub(r'[^a-z0-9]', '', v)}"
        for k, v in (p.split("=", 1) for p in query.split("&") if "=" in p)
    )
    if pfad.endswith("/"):
        return pfad.lstrip("/") + f"index{zusatz}.html"
    return pfad.lstrip("/")


def _relativ(von_datei: str, zu_datei: str) -> str:
    return posixpath.relpath(zu_datei, posixpath.dirname(von_datei) or ".")


class Command(BaseCommand):
    help = "Schreibt die Demo-Firma als statische Klick-Demo (nur mit DJANGO_DEBUG=true, nur Demo-Daten)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("ziel", help="Zielordner, wird geleert")

    def handle(self, *args: Any, **optionen: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("Nur in der lokalen Entwicklung oder CI (DJANGO_DEBUG=true).")
        firma = Firma.objects.filter(name=DEMO_FIRMA).first()
        nutzer = Nutzer.objects.filter(email=EMAIL).first()
        if firma is None or nutzer is None:
            raise CommandError("Keine Demo-Firma. Zuerst `manage.py demo_daten` ausführen.")
        ziel = Path(optionen["ziel"])
        if ziel.exists():
            shutil.rmtree(ziel)
        ziel.mkdir(parents=True)

        client = Client(HTTP_HOST="localhost")
        client.force_login(nutzer)
        sitzung = client.session
        sitzung[ZWEITER_FAKTOR_OK] = True
        sitzung[FIRMA] = firma.pk
        sitzung.save()

        seiten: dict[str, str] = {}  # URL-Pfad → HTML
        dateien: dict[str, bytes] = {}
        warteschlange = list(START)
        gesehen = set(warteschlange)
        while warteschlange and len(seiten) < MAX_SEITEN:
            pfad = warteschlange.pop(0)
            antwort = client.get(pfad)
            if antwort.status_code != 200:
                continue
            typ = antwort.get("Content-Type", "")
            if not typ.startswith("text/html"):
                if pfad.endswith(ERLAUBTE_DATEIEN):
                    dateien[pfad] = antwort.content
                continue
            html = antwort.content.decode()
            seiten[pfad] = html
            for treffer in LINK.finditer(html):
                kandidat = _schluessel(treffer.group("url"), pfad)
                if kandidat is None or kandidat in gesehen or kandidat.startswith(STATIC):
                    continue
                if treffer.group("attr") == "action":
                    continue
                if kandidat.startswith(AUSGESCHLOSSEN) and not kandidat.startswith(TROTZDEM):
                    continue
                gesehen.add(kandidat)
                warteschlange.append(kandidat)

        statisch: set[str] = set()
        for pfad, html in seiten.items():
            datei = _datei(pfad)
            html = self._umschreiben(html, datei, set(seiten) | set(dateien), statisch, pfad)
            (ziel / datei).parent.mkdir(parents=True, exist_ok=True)
            (ziel / datei).write_text(html, encoding="utf-8")
        for pfad, inhalt in dateien.items():
            (ziel / _datei(pfad)).parent.mkdir(parents=True, exist_ok=True)
            (ziel / _datei(pfad)).write_bytes(inhalt)
        # Auch Dateien, die erst ein Stylesheet nachlädt (Schriften, Bilder)
        for name in sorted(statisch):
            if name.endswith(".css") and (quelle := finders.find(name)):
                basis = posixpath.dirname(name)
                for url in re.findall(r'url\("?([^")]+)"?\)', Path(str(quelle)).read_text(encoding="utf-8")):
                    if not url.startswith(("data:", "http", "/")):
                        statisch.add(posixpath.normpath(posixpath.join(basis, url)))
        for name in sorted(statisch):
            quelle = finders.find(name)
            if quelle:
                (ziel / "static" / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(str(quelle), ziel / "static" / name)
        (ziel / "static" / "demo").mkdir(parents=True, exist_ok=True)
        (ziel / "static" / "demo" / "demo.css").write_text(DEMO_CSS, encoding="utf-8")
        (ziel / "static" / "demo" / "demo.js").write_text(DEMO_JS, encoding="utf-8")
        (ziel / ".nojekyll").write_text("", encoding="utf-8")
        self.stdout.write(f"{len(seiten)} Seiten und {len(dateien)} Dateien nach {ziel} geschrieben.")

    def _umschreiben(self, html: str, datei: str, vorhanden: set[str], statisch: set[str], seite: str = "/") -> str:
        # Kein CSRF-Token und kein htmx in der statischen Demo
        html = re.sub(r'<input type="hidden" name="csrfmiddlewaretoken" value="[^"]*">', "", html)
        html = re.sub(r"\s+hx-headers='[^']*'", "", html)
        html = re.sub(r'<script src="[^"]*htmx[^"]*"[^>]*></script>\s*', "", html)
        html = re.sub(r'\s*<meta name="htmx-config"[^>]*>', "", html)
        html = re.sub(r'\s+hx-(?:post|target|swap|trigger|select|push-url)="[^"]*"', "", html)

        def ersetzen(treffer: re.Match[str]) -> str:
            attr, url = treffer.group("attr"), treffer.group("url")
            pfad = urlsplit(url).path
            if pfad.startswith(STATIC):
                name = pfad[len(STATIC) :]
                statisch.add(name)
                return f'{attr}="{_relativ(datei, "static/" + name)}"'
            if attr == "action":
                return 'action="#"'
            ziel = _schluessel(url, seite)
            if attr == "hx-get":
                if ziel in vorhanden:
                    return f'data-demo-href="{_relativ(datei, _datei(ziel))}"'
                return ""
            if ziel in vorhanden and ziel is not None:
                return f'{attr}="{_relativ(datei, _datei(ziel))}"'
            return f'{attr}="#" data-demo-aus="1"'

        html = LINK.sub(ersetzen, html)
        css = _relativ(datei, "static/demo/demo.css")
        js = _relativ(datei, "static/demo/demo.js")
        html = html.replace("</head>", f'  <link rel="stylesheet" href="{css}">\n</head>', 1)
        html = re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + BANNER, html, count=1)
        html = html.replace("</body>", f'<script src="{js}" defer></script>\n</body>', 1)
        html = html.replace("<title>", "<title>Demo · ", 1)
        return html
