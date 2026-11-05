"""Prüft die Mindestabdeckung (Teststrategie): dunning und capture/rules je mindestens 90 % Zeilen.

Liest die `.coverage`-Datei des vorherigen pytest-Laufs. Bereiche, die es noch nicht gibt, werden übersprungen.
"""

import io
import sys
from pathlib import Path

from coverage import Coverage
from coverage.exceptions import NoDataError

MINDEST = 90.0
BEREICHE = {"dunning": ["dunning/*.py"], "capture/rules": ["capture/rules.py"]}
WURZEL = Path(__file__).resolve().parent.parent


def main() -> int:
    cov = Coverage(data_file=str(WURZEL / ".coverage"))
    cov.load()
    fehler = False
    for name, muster in BEREICHE.items():
        dateien = [d for m in muster for d in WURZEL.glob(m) if d.stat().st_size > 0]
        if not dateien:
            print(f"{name}: noch nicht vorhanden, übersprungen")
            continue
        try:
            prozent = cov.report(include=[str(d) for d in dateien], file=io.StringIO())
        except NoDataError:
            print(f"{name}: keine Messdaten, Tests fehlen")
            fehler = True
            continue
        status = "ok" if prozent >= MINDEST else "ZU NIEDRIG"
        print(f"{name}: {prozent:.1f} % ({status}, Vorgabe {MINDEST:.0f} %)")
        fehler |= prozent < MINDEST
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
