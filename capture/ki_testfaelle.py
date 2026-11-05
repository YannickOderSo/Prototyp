"""KI-Testfälle (KI-Pipeline, Qualitätssicherung): Fälle laden, mit dem Modell ausführen, bewerten.

Im Standard-Testlauf wird das Modell gemockt (die Fälle enthalten eine Beispielantwort). Gegen das echte
Modell läuft nur `manage.py ki_testfaelle` mit Schlüsseln aus Umgebungsvariablen.
Abnahme laut Vault: mindestens 11 von 12 Fällen, alle Sicherheitsfälle grün.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.db import transaction

from accounts.models import Firma
from ledger.models import Artikel, Kontakt

from . import aufbereitung, rules
from .dateien import speichern
from .extraktion import extrahieren
from .models import Erfassung

ORDNER = Path(__file__).resolve().parent.parent / "tests" / "ki_faelle"


@dataclass
class Fall:
    name: str
    beschreibung: str
    sicherheit: bool
    quellen: list[dict[str, str]]
    erwartet: dict[str, Any]
    beispielantwort: dict[str, Any]
    bilder: list[str] = field(default_factory=list)
    csv: list[str] = field(default_factory=list)


@dataclass
class Ergebnis:
    fall: Fall
    abweichungen: list[str]
    ki: dict[str, Any] = field(default_factory=dict)
    fehler: str = ""

    @property
    def bestanden(self) -> bool:
        return not self.abweichungen and not self.fehler


def faelle_laden(ordner: Path = ORDNER) -> list[Fall]:
    return [Fall(**json.loads(p.read_text(encoding="utf-8"))) for p in sorted(ordner.glob("[0-9]*.json"))]


def stammdaten_laden(ordner: Path = ORDNER) -> dict[str, Any]:
    daten: dict[str, Any] = json.loads((ordner / "stammdaten.json").read_text(encoding="utf-8"))
    return daten


def _firma_anlegen(stamm: dict[str, Any]) -> Firma:
    firma = Firma.objects.create(name="KI-Testfälle (temporär)")
    for k in stamm["kunden"]:
        Kontakt.objects.create(firma=firma, extern_id=k["extern_id"], name=k["name"], kundennummer=k["kundennummer"])
    for a in stamm["artikel"]:
        Artikel.objects.create(
            firma=firma,
            extern_id=a["extern_id"],
            bezeichnung=a["bezeichnung"],
            einheit=a["einheit"],
            netto=Decimal(a["netto"]),
            steuersatz=Decimal(a["steuersatz"]),
            typ=a["typ"],
        )
    from ledger.models import Beleg

    for an in stamm.get("angebote", []):
        kontakt = Kontakt.objects.get(firma=firma, extern_id=an["kunde_extern_id"])
        Beleg.objects.create(
            firma=firma, extern_id=an["extern_id"], art="angebot", nummer=an["nummer"], kontakt=kontakt, status="offen"
        )
    return firma


def _entwurf(fall: Fall, ki: dict[str, Any], erfassung: Erfassung, stamm: dict[str, Any]) -> rules.Entwurf:
    kontakte = [rules.KontaktInfo(k["extern_id"], k["name"], k["kundennummer"]) for k in stamm["kunden"]]
    artikel = {
        a["extern_id"]: rules.ArtikelInfo(
            a["extern_id"], a["bezeichnung"], a["einheit"], Decimal(a["netto"]), Decimal(a["steuersatz"]), a["typ"]
        )
        for a in stamm["artikel"]
    }
    angebot = next(
        (
            rules.AngebotInfo(
                an["nummer"], an["kunde_extern_id"], tuple((p[0], Decimal(p[1])) for p in an["positionen"])
            )
            for an in stamm.get("angebote", [])
            if an["nummer"] == ki.get("angebot_nummer")
        ),
        None,
    )
    return rules.entwurf_bilden(
        ki,
        kontakte,
        artikel,
        quelltexte=[erfassung.transkript, erfassung.notiz, *(str(q.get("text", "")) for q in erfassung.quellen)],
        stunden=[s for q in erfassung.quellen for s in q.get("stunden", [])],
        angebot=angebot,
    )


def ausfuehren(fall: Fall, ordner: Path = ORDNER) -> Ergebnis:
    """Führt einen Fall in einer Transaktion aus, die anschließend zurückgerollt wird (keine Spuren in der DB)."""
    stamm = stammdaten_laden(ordner)
    ergebnis = Ergebnis(fall, [])
    with transaction.atomic():
        firma = _firma_anlegen(stamm)
        erfassung = Erfassung.objects.create(
            firma=firma,
            kanal="upload",
            status="extrahiert",
            transkript="\n".join(q["text"] for q in fall.quellen if q["herkunft"] == "gesprochen"),
            notiz="\n".join(q["text"] for q in fall.quellen if q["herkunft"] == "notiz"),
            quellen=[
                {"art": q["herkunft"], "name": q["name"], "herkunft": q["herkunft"], "text": q["text"], "stunden": []}
                for q in fall.quellen
                if q["herkunft"] not in ("gesprochen", "notiz")
            ]
            + [aufbereitung.zeiterfassung(name, (ordner / name).read_bytes()).als_dict() for name in fall.csv],
        )
        for name in fall.bilder:
            speichern(erfassung, name, (ordner / name).read_bytes())
        try:
            ki, _ = extrahieren(erfassung)
        except Exception as fehler:
            ergebnis.fehler = f"{type(fehler).__name__}: {fehler}"
        else:
            ergebnis.ki = ki
            ergebnis.abweichungen = bewerten(fall, ki, _entwurf(fall, ki, erfassung, stamm))
        transaction.set_rollback(True)
    return ergebnis


def bewerten(fall: Fall, ki: dict[str, Any], entwurf: rules.Entwurf) -> list[str]:
    e = fall.erwartet
    abw: list[str] = []
    if "belegart" in e and entwurf.belegart != e["belegart"]:
        abw.append(f"Belegart {entwurf.belegart!r} statt {e['belegart']!r}")
    if "kunde" in e and entwurf.kunde_name != e["kunde"]:
        abw.append(f"Kunde {entwurf.kunde_name!r} statt {e['kunde']!r}")
    if "kunde_enthaelt" in e and e["kunde_enthaelt"].lower() not in str(ki.get("kunde", "")).lower():
        abw.append(f"Kunde {ki.get('kunde')!r} enthält nicht {e['kunde_enthaelt']!r}")
    if e.get("kunde_unbekannt") and entwurf.kunde_extern_id:
        abw.append("Unbekannter Kunde wurde einem bestehenden Kontakt zugeordnet")
    for soll in e.get("positionen", []):
        if not any(
            p.artikel_id == soll["artikel_id"] and p.menge == Decimal(str(soll["menge"])) for p in entwurf.positionen
        ):
            gefunden = [(p.artikel_id, str(p.menge)) for p in entwurf.positionen]
            abw.append(f"Position {soll['artikel_id']} × {soll['menge']} fehlt (gefunden: {gefunden})")
    if "positionen_anzahl" in e and len(entwurf.positionen) != e["positionen_anzahl"]:
        abw.append(f"{len(entwurf.positionen)} Positionen statt {e['positionen_anzahl']}")
    for feld in ("leistung_von", "leistung_bis"):
        if feld in e and str(getattr(entwurf, feld) or "") != e[feld]:
            abw.append(f"{feld} {getattr(entwurf, feld)} statt {e[feld]}")
    if "angebot_nummer" in e and entwurf.angebot_nummer != e["angebot_nummer"]:
        abw.append(f"Angebot {entwurf.angebot_nummer!r} statt {e['angebot_nummer']!r}")
    if e.get("offene_fragen_nicht_leer") and not [f for f in ki.get("offene_fragen", []) if str(f).strip()]:
        abw.append("Keine offene Frage, obwohl erwartet")
    if "hinweis_enthaelt" in e and not any(e["hinweis_enthaelt"] in h for h in entwurf.hinweise):
        abw.append(f"Hinweis mit {e['hinweis_enthaelt']!r} fehlt")
    if "blocker_enthaelt" in e and not any(e["blocker_enthaelt"] in b for b in entwurf.blocker):
        abw.append(f"Blocker mit {e['blocker_enthaelt']!r} fehlt")
    if e.get("position_ohne_artikel") and not any(not p.artikel_id and p.netto is None for p in entwurf.positionen):
        abw.append("Erwartete Position ohne Artikel und ohne Preis fehlt")
    if e.get("preis_aus_artikel") and any(p.netto is not None and not p.artikel_id for p in entwurf.positionen):
        abw.append("Preis stammt nicht aus einem Artikel")
    if e.get("kein_zeiterfassung_hinweis") and any(h.startswith("Zeiterfassung:") for h in entwurf.hinweise):
        abw.append("Abweichung zur Zeiterfassung")
    return abw


def abnahme(ergebnisse: list[Ergebnis], mindestens: int = 11) -> tuple[bool, str]:
    bestanden = sum(1 for e in ergebnisse if e.bestanden)
    sicherheit_ok = all(e.bestanden for e in ergebnisse if e.fall.sicherheit)
    ok = bestanden >= min(mindestens, len(ergebnisse)) and sicherheit_ok
    sicherheit = "alle grün" if sicherheit_ok else "NICHT alle grün"
    text = f"{bestanden}/{len(ergebnisse)} bestanden, Sicherheitsfälle {sicherheit}"
    return ok, text
