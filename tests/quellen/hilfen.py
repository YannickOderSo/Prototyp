"""Hilfen für Tests der Rechnungskopien: Beispieldateien und ein ZUGFeRD-PDF mit eingebettetem XML."""

import io
from pathlib import Path

DATEIEN = Path(__file__).parent / "dateien"


def datei(name: str) -> bytes:
    return (DATEIEN / name).read_bytes()


def zugferd_pdf(xml: bytes, name: str = "factur-x.xml") -> bytes:
    from pypdf import PdfWriter

    schreiber = PdfWriter()
    schreiber.add_blank_page(width=595, height=842)
    schreiber.add_attachment(name, xml)
    puffer = io.BytesIO()
    schreiber.write(puffer)
    return puffer.getvalue()


def pdf_ohne_xml() -> bytes:
    from pypdf import PdfWriter

    schreiber = PdfWriter()
    schreiber.add_blank_page(width=595, height=842)
    puffer = io.BytesIO()
    schreiber.write(puffer)
    return puffer.getvalue()


def cii(nummer: str = "RE-2026-0412", **ersetzen: str) -> bytes:
    """Die CII-Beispieldatei mit geänderten Werten (z. B. andere Nummer, Typ oder Beträge)."""
    text = datei("xrechnung_cii.xml").decode().replace("RE-2026-0412", nummer)
    for alt, neu in ersetzen.items():
        text = text.replace(alt.replace("__", "-"), neu)
    return text.encode()
