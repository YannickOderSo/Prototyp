# ADR-002: Python/Django in einem neuen Repository, Belegfluss-Teile portierbar

Status: angenommen · 5. November 2026 · kann vom Team vor M0 durch ein neues ADR ersetzt werden

## Kontext
Yannick möchte, dass das Produkt nicht wie Belegfluss aufgebaut sein muss. Belegfluss (Lukas, Python/Django) enthält trotzdem geprüfte, wiederverwendbare Logik: Regel-Engine "KI ordnet zu, Regeln rechnen", Extraktion per JSON-Schema mit Prompt-Injection-Schutz, CSV-Zeiterfassung, Lexware-Entwurfspfad. Drei Code-Reviews fanden aber Betriebs- und Steuerfehler sowie eine Doppelarchitektur.

## Entscheidung
Neues Repository `Prototyp` mit eigener, sauberer Struktur. Stack: Python 3.12, Django 5.2 LTS, Postgres 16, HTMX, eigene Postgres-Job-Queue, Docker Compose, Caddy. Umgang mit Belegfluss-Code regelt ADR-007: Eigenbau als Standard, Übernahme nur in klar begründeten Fällen mit eigenen Tests (Nutzung von Lukas am 2026-11-05 freigegeben). Das eigene Rechnungsprogramm aus Belegfluss wird nicht übernommen (ADR-001).

## Folgen
+ Wiederverwendung der wertvollen Domänenlogik, ein Stack für Web, Worker und KI, gute Bibliotheken für spätere E-Rechnung (factur-x) falls Keil B kommt.
- Wer nur TypeScript kennt, braucht Einarbeitung; Django ist dafür vergleichsweise zugänglich.
