"""Datenexport je Firma (F3): CSV aller Vorschläge, Versände und des Protokolls, als ZIP.

CSV-Injection-Schutz (Sicherheit-Datenschutz-Betrieb.md): Zellen, die mit = + - @ (oder Tab/CR) beginnen,
bekommen ein vorangestelltes Hochkomma. Trennzeichen Semikolon, UTF-8 mit BOM (Excel).
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections.abc import Iterable, Sequence
from typing import Any

from django.utils import timezone

from accounts.models import Firma
from audit.models import Protokolleintrag
from capture.models import Erfassung
from dunning.models import Mahnvorschlag, Versand

GEFAEHRLICH = ("=", "+", "-", "@", "\t", "\r")


def zelle(wert: Any) -> str:
    if wert is None:
        return ""
    if isinstance(wert, dict | list):
        text = json.dumps(wert, ensure_ascii=False)
    elif hasattr(wert, "isoformat"):
        text = wert.isoformat()
    else:
        text = str(wert)
    return "'" + text if text.startswith(GEFAEHRLICH) else text


def csv_text(kopf: Sequence[str], zeilen: Iterable[Sequence[Any]]) -> str:
    puffer = io.StringIO()
    puffer.write("﻿")
    schreiber = csv.writer(puffer, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    schreiber.writerow(kopf)
    for zeile in zeilen:
        schreiber.writerow([zelle(w) for w in zeile])
    return puffer.getvalue()


def vorschlaege(firma: Firma) -> str:
    kopf = [
        "id",
        "beleg",
        "kunde",
        "stufe",
        "status",
        "erstellt_am",
        "offen",
        "zinsen",
        "pauschale",
        "gesamt",
        "verzugsbeginn",
        "versandart",
        "freigegeben_von",
        "freigegeben_am",
        "versendet_am",
        "verworfen_grund",
        "lexware_mahnung_id",
    ]
    qs = Mahnvorschlag.objects.fuer(firma).select_related("beleg", "freigegeben_von").order_by("pk")
    return csv_text(
        kopf,
        (
            [
                v.pk,
                v.beleg.nummer,
                v.beleg.kontakt_name,
                v.get_stufe_display(),
                v.status,
                v.erstellt_am,
                v.offen_betrag,
                v.zinsen,
                v.pauschale,
                v.gesamt,
                v.verzugsbeginn,
                v.versandart,
                v.freigegeben_von.email if v.freigegeben_von else "",
                v.freigegeben_am,
                v.versendet_am,
                v.verworfen_grund,
                v.lexware_dunning_id,
            ]
            for v in qs
        ),
    )


def versaende(firma: Firma) -> str:
    kopf = ["id", "vorschlag", "empfaenger", "betreff", "anhang", "message_id", "gesendet_am", "zustellfehler"]
    qs = Versand.objects.fuer(firma).order_by("pk")
    return csv_text(
        kopf,
        (
            [v.pk, v.vorschlag_id, v.empfaenger, v.betreff, v.anhang_name, v.message_id, v.gesendet_am, v.zustellfehler]
            for v in qs
        ),
    )


def protokoll(firma: Firma) -> str:
    kopf = ["id", "zeit", "nutzer", "ereignis", "objekt_typ", "objekt_id", "daten"]
    qs = Protokolleintrag.objects.filter(firma=firma).select_related("nutzer").order_by("zeit", "id")
    return csv_text(
        kopf,
        (
            [p.pk, p.zeit, p.nutzer.email if p.nutzer else "System", p.ereignis, p.objekt_typ, p.objekt_id, p.daten]
            for p in qs
        ),
    )


def erfassungen(firma: Firma) -> str:
    kopf = ["id", "erstellt", "kanal", "status", "kunde", "belegart", "lexware_id", "freigegeben_am"]
    qs = Erfassung.objects.fuer(firma).order_by("pk")
    return csv_text(
        kopf,
        (
            [
                e.pk,
                e.erstellt,
                e.kanal,
                e.status,
                e.entwurf.get("kunde_name", ""),
                e.entwurf.get("belegart", ""),
                e.ziel_extern_id,
                e.freigegeben_am,
            ]
            for e in qs
        ),
    )


def zip_export(firma: Firma) -> bytes:
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as archiv:
        archiv.writestr("vorschlaege.csv", vorschlaege(firma))
        archiv.writestr("versaende.csv", versaende(firma))
        archiv.writestr("protokoll.csv", protokoll(firma))
        archiv.writestr("erfassungen.csv", erfassungen(firma))
        archiv.writestr(
            "LIESMICH.txt",
            f"Export für {firma.name}, erstellt {timezone.localtime():%d.%m.%Y %H:%M} Uhr.\r\n"
            "Trennzeichen Semikolon, Zeichensatz UTF-8. Zellen, die mit = + - @ beginnen, sind zum Schutz\r\n"
            "vor Formel-Ausführung mit einem Hochkomma versehen.\r\n",
        )
    return puffer.getvalue()
