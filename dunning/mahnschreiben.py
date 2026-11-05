"""Mahnschreiben als PDF für importierte Posten (ADR-008, H8).

Für Rechnungen aus Lexware liefert Lexware das PDF. Importierte Posten kennt Lexware nicht; dafür erzeugt die App
einen Brief mit genau dem Text der Mail (D10: Vorschau, Mail und Brief stimmen überein). Der Brief ist keine
Rechnung und trägt keine Rechnungsnummer der App.
"""

from __future__ import annotations

import io
from datetime import date
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .mail import inhalt
from .models import Mahnvorschlag

TITEL = {0: "Zahlungserinnerung", 1: "Mahnung", 2: "2. Mahnung"}


def _absatz(text: str, stil: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), stil)


def pdf(vorschlag: Mahnvorschlag, versandtag: date | None = None) -> bytes:
    versandtag = versandtag or timezone.localdate()
    firma = vorschlag.firma
    beleg = vorschlag.beleg
    kontakt = beleg.kontakt
    mail = inhalt(vorschlag, versandtag)
    klein = ParagraphStyle("klein", fontName="Helvetica", fontSize=7.5, leading=10, textColor="#555555")
    normal = ParagraphStyle("normal", fontName="Helvetica", fontSize=10.5, leading=14.5)
    rechts = ParagraphStyle("rechts", parent=normal, alignment=2)
    fett = ParagraphStyle("fett", parent=normal, fontName="Helvetica-Bold", fontSize=12, leading=16)

    absender = " · ".join(x for x in (firma.name, firma.strasse, f"{firma.plz} {firma.ort}".strip()) if x)
    name = kontakt.name if kontakt else beleg.kontakt_name
    empfaenger = "\n".join(x for x in (name, kontakt.adresse if kontakt else "") if x)
    ort_datum = f"{firma.ort + ', ' if firma.ort else ''}{versandtag:%d.%m.%Y}"
    absaetze = [a.strip() for a in mail.text.split("\n\n") if a.strip()]

    puffer = io.BytesIO()
    dokument = SimpleDocTemplate(
        puffer,
        pagesize=A4,
        leftMargin=25 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=f"{TITEL[vorschlag.stufe]} {beleg.nummer}",
        author=firma.name,
    )
    inhalt_ = [
        _absatz(absender, klein),
        Spacer(1, 3 * mm),
        _absatz(empfaenger or "(Empfänger)", normal),
        Spacer(1, 18 * mm),
        _absatz(ort_datum, rechts),
        Spacer(1, 8 * mm),
        _absatz(mail.betreff, fett),
        Spacer(1, 6 * mm),
    ]
    for absatz in absaetze:
        inhalt_ += [_absatz(absatz, normal), Spacer(1, 3.5 * mm)]
    dokument.build(inhalt_)
    return puffer.getvalue()
