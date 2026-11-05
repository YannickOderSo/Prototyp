"""Startet die Playwright-Tests (tests/e2e, Marker e2e). Ohne gesammelte Tests endet der Lauf mit Hinweis."""

import subprocess
import sys

ergebnis = subprocess.run([sys.executable, "-m", "pytest", "-m", "e2e", "-p", "no:cacheprovider"], check=False)
# pytest-Code 5 = keine Tests gesammelt
if ergebnis.returncode == 5:
    print("Noch keine E2E-Tests vorhanden.")
    sys.exit(0)
sys.exit(ergebnis.returncode)
