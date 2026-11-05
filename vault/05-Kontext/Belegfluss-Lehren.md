# Lehren aus Belegfluss

Repository: https://github.com/9ykvwrv2df-lgtm/belegfluss (Lukas, erster Commit 4. November 2026). Drei statische Reviews, Reifegrad 4 bis 6 von 10.

## Als Orientierung nutzen (Code-Übernahme nur nach ADR-007)

Lukas hat die Nutzung am 5. November 2026 freigegeben. Standard bleibt Eigenbau; die folgenden Stellen lohnen sich zum Nachlesen:

- Trennung KI ordnet zu, Regeln rechnen (`belegfluss/regeln.py`, `belegfluss/extraktion.py`).
- Prompt-Injection als eigener Testfall; Quellen als Daten Dritter im System-Prompt.
- CSV-Zeiterfassung deterministisch verdichten (`belegfluss/quellen.py`).
- Lexware-Entwurfspfad ohne `finalize`, Trockenlauf-Schalter (`belegfluss/lexware.py`).
- Fernet-Verschlüsselung von Zugangsdaten, TOTP mit Replay-Schutz, Mandantentests.
- Ehrliche "Noch nicht fertig"-Liste im README.

## Nicht wiederholen

- Nie gegen echte Systeme getestet: hier gehört ein Echtlauf mit Lexware-Testkonto zu jedem Meilenstein.
- Worker als ein synchroner Loop ohne Timeouts: hier Job-Queue mit Isolation je Firma, IMAP mit Timeout.
- Absenderprüfung nur über From-Header: hier DKIM/SPF über `Authentication-Results`.
- Login-Sperre nur je E-Mail: hier zusätzlich je IP.
- Deploy vom Laptop, Backups unverschlüsselt am selben Ort: hier CI-Deploy und restic offsite.
- Zwei Architekturen nebeneinander (CLI-Bot und Web-App): hier nur die Web-App.
- Landingpage verspricht Funktionen, die es nicht gibt: Marketing nur für Gebautes.
- Steuerfehler im eigenen Rechnungsprogramm: hier gar kein eigenes Rechnungsprogramm.
