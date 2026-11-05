# ADR-004: Alles mit Außenwirkung braucht menschliche Freigabe

Status: angenommen · 5. November 2026

## Kontext
Yannicks Idee sah einen KI-Agenten vor, der Rechnungen selbständig erstellt. Der Betrieb haftet für falschen Steuerausweis (§ 14c UStG) und bleibt nach GoBD allein verantwortlich. Spracherkennung macht bei Dialekt und Zahlen messbar Fehler. Kein Wettbewerber versendet ohne Freigabe.

## Entscheidung
Die KI erzeugt nur Entwürfe. Rechnungs- und Angebotsentwürfe werden im Bestandstool vom Nutzer abgeschlossen. Mahnungen gehen erst nach Freigabe durch Inhaber oder Freigeber mit Login und 2FA hinaus. Ein Link in einer Mail gibt nie selbst etwas frei.

## Folgen
Weniger "Magie" im Marketing, dafür vertrauenswürdig. Positionierung: "Entwurf in 60 Sekunden, Sie geben frei."
