#!/usr/bin/env python3
"""Nachbau der benötigten restic-Befehle für Tests der Sicherungsskripte (kein echtes Repository).

Ablage in $FAKE_RESTIC_DIR: je Snapshot eine Datei `<id>` mit dem Inhalt und `index.json` mit Metadaten,
dazu `aufrufe.log` mit allen Aufrufen. `--stdin-from-command` verhält sich wie bei restic >= 0.17:
schlägt der Befehl fehl, entsteht kein Snapshot und der Exit-Code ist ungleich 0.
"""

import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ORDNER = Path(os.environ["FAKE_RESTIC_DIR"])
INDEX = ORDNER / "index.json"


def index() -> list[dict]:
    return json.loads(INDEX.read_text()) if INDEX.exists() else []


def main(argumente: list[str]) -> int:
    ORDNER.mkdir(parents=True, exist_ok=True)
    with (ORDNER / "aufrufe.log").open("a") as log:
        log.write(" ".join(argumente) + "\n")
    befehl = argumente[0]
    if befehl == "backup":
        trenner = argumente.index("--")
        optionen, kommando = argumente[1:trenner], argumente[trenner + 1 :]
        assert "--stdin-from-command" in optionen
        ergebnis = subprocess.run(kommando, capture_output=True)
        if ergebnis.returncode != 0:
            sys.stderr.write(ergebnis.stderr.decode())
            return 1
        sid = uuid.uuid4().hex[:8]
        (ORDNER / sid).write_bytes(ergebnis.stdout)
        alter = float(os.environ.get("FAKE_RESTIC_ALTER_STUNDEN", "0"))
        zeit = (datetime.now(UTC) - timedelta(hours=alter)).astimezone().isoformat()
        tag = optionen[optionen.index("--tag") + 1]
        name = optionen[optionen.index("--stdin-filename") + 1]
        INDEX.write_text(json.dumps([*index(), {"short_id": sid, "time": zeit, "tags": [tag], "datei": name}]))
        return 0
    if befehl == "snapshots":
        tag = argumente[argumente.index("--tag") + 1]
        treffer = [s for s in index() if tag in s["tags"]]
        print(json.dumps(treffer[-1:]))
        return 0
    if befehl == "dump":
        sid, name = argumente[1], argumente[2]
        eintraege = index()
        eintrag = (
            eintraege[-1]
            if sid == "latest" and eintraege
            else next((s for s in eintraege if s["short_id"] == sid), None)
        )
        if eintrag is None or eintrag["datei"] != name:
            return 1
        sys.stdout.buffer.write((ORDNER / eintrag["short_id"]).read_bytes())
        return 0
    if befehl in {"forget", "check"}:
        return 0
    return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
