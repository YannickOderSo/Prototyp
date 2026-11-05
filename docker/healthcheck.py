"""Docker-Healthcheck für den Web-Container: ruft /healthz über Gunicorn auf (Host aus DJANGO_ALLOWED_HOSTS).

Gesund heißt hier: Gunicorn antwortet. Ein 503 von /healthz (z. B. Worker ausgefallen) meldet der externe
Uptime-Check; der Web-Container selbst bleibt dabei gesund, damit Caddy weiter ausliefert.
"""

import os
import sys
import urllib.error
import urllib.request

host = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost").split(",")[0].strip() or "localhost"
anfrage = urllib.request.Request("http://127.0.0.1:8000/healthz", headers={"Host": host, "X-Forwarded-Proto": "https"})
try:
    with urllib.request.urlopen(anfrage, timeout=5) as antwort:  # noqa: S310 (feste lokale URL)
        sys.exit(0 if antwort.status == 200 else 1)
except urllib.error.HTTPError as fehler:
    sys.exit(0 if fehler.code == 503 else 1)
except (urllib.error.URLError, OSError):
    sys.exit(1)
