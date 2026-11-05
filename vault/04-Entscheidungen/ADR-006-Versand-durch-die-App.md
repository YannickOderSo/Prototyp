# ADR-006: Erinnerungen und Mahnungen versendet die App per E-Mail

Status: angenommen · 5. November 2026

Die Lexware-API legt Mahnungen nur als Entwurf an und beschreibt keinen E-Mail-Versand (geprüft am 5. November 2026). Deshalb holt die App das PDF (`/v1/dunnings/{id}/file` bzw. `/v1/invoices/{id}/file`) und versendet selbst, mit Absendername und Reply-To der Firma. Für Stufe 0 (Zahlungserinnerung) wird keine Lexware-Mahnung angelegt. Ist der Kontakt ohne E-Mail, zeigt die App "Postversand nötig" und stellt das PDF zum Download bereit.
