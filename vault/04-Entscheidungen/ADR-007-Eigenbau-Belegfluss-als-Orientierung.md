# ADR-007: Eigenbau von Grund auf, Belegfluss nur als Orientierung

Status: angenommen · 5. November 2026 · ergänzt ADR-002

## Kontext
Lukas hat am 5. November 2026 zugestimmt, dass Code aus seinem Repository `belegfluss` genutzt werden darf. Yannick und Lukas wollen trotzdem in einem eigenen Workflow von Grund auf etwas Eigenes bauen. Belegfluss soll eher Orientierung sein.

## Entscheidung
- Standard ist **Eigenbau**: Struktur, Datenmodell, Module und Tests entstehen neu nach diesem Vault.
- Belegfluss ist **Nachschlagewerk**: Wie wurde ein Problem gelöst, welche Fallstricke gab es, welche Testfälle sind sinnvoll?
- **Übernahme von Code nur, wenn alle drei Bedingungen gelten:**
  1. Der Teil ist klar abgegrenzt und fachlich aufwendig (z. B. CSV-Zeiterfassung verdichten, Prompt-Injection-Testfälle, einzelne Prüfregeln).
  2. Er passt ohne Umbau des eigenen Datenmodells oder lässt sich in unter einer Stunde anpassen.
  3. Er bekommt eigene Tests in diesem Repository, bevor er verwendet wird.
- Übernommene Stellen werden im Commit und im Code-Kommentar mit Herkunft markiert: `# Angelehnt an belegfluss/<datei>.py (Lukas Welker, Nutzung freigegeben am 2026-11-05)`.
- **Nicht übernehmen:** eigenes Rechnungsprogramm, E-Rechnungs-Erzeugung, Nummernkreise, CLI-Bot, Worker-Loop, Deploy-Skripte, Landingpages (siehe ADR-001 und `05-Kontext/Belegfluss-Lehren.md`).

## Folgen
+ Saubere, einheitliche Codebasis, die das Team selbst versteht.
+ Bewährte Ideen und Testfälle gehen nicht verloren.
- Etwas mehr Aufwand als reines Kopieren; bewusst in Kauf genommen.
