"""Nachgebildeter Bedrock-Client für den Standard-Testlauf (KI-Aufrufe werden immer gemockt)."""

import json
from types import SimpleNamespace


class FakeMessages:
    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.aufrufe = []

    def create(self, **kwargs):
        self.aufrufe.append(kwargs)
        antwort = self.antworten.pop(0) if len(self.antworten) > 1 else self.antworten[0]
        if isinstance(antwort, Exception):
            raise antwort
        return antwort


class FakeClient:
    def __init__(self, *antworten):
        self.messages = FakeMessages(antworten)


def antwort(daten=None, stop_reason="end_turn", text=None, eingabe=1200, ausgabe=300):
    inhalt = text if text is not None else json.dumps(daten, ensure_ascii=False)
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=inhalt)],
        usage=SimpleNamespace(input_tokens=eingabe, output_tokens=ausgabe),
    )


def ergebnis(**ueberschreiben):
    daten = {
        "belegart": "rechnung",
        "kunde": "Bau AG",
        "angebot_nummer": "",
        "leistung_von": "2026-11-02",
        "leistung_bis": "2026-11-04",
        "positionen": [
            {
                "artikel_id": "art-maler-stunde",
                "beschreibung": "Malerarbeiten",
                "menge": 12,
                "einheit": "Stunde",
                "quelle": "Sprachmemo",
                "herkunft": "gesprochen",
            },
        ],
        "offene_fragen": [],
    }
    daten.update(ueberschreiben)
    return daten
