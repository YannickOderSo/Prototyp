# Mahnlogik und rechtliche Regeln

Keine Rechtsberatung. Alle Texte und Regeln vor dem ersten Pilotkunden von einem Anwalt oder Steuerberater prüfen lassen (Ticket M4-07). Wo das Recht unklar ist, gilt: **die für den Schuldner günstigere Auslegung**, also lieber zu wenig Zinsen als zu viel.

## Stufen

| Stufe | Name | Standard-Auslöser | Inhalt | Lexware-Mahnung |
| --- | --- | --- | --- | --- |
| 0 | Zahlungserinnerung | 7 Tage nach Fälligkeit | freundlich, Rechnungs-PDF anbei, keine Zinsen, keine Pauschale | nein |
| 1 | 1. Mahnung | 21 Tage nach Fälligkeit und mindestens 10 Tage nach Stufe 0 | offener Betrag, ggf. Zinsen und Pauschale, neue Frist 10 Tage | ja, Entwurf in Lexware, PDF anbei |
| 2 | 2. Mahnung | 35 Tage nach Fälligkeit und mindestens 10 Tage nach Stufe 1 | wie 1, Hinweis auf mögliches gerichtliches Mahnverfahren, neue Frist 7 Tage | ja |
| danach | Klärung | keine Automatik | Posten erscheint als "manuell klären" im Cockpit; kein Inkasso, kein Mahnbescheid aus der App | nein |

Abstände sind je Firma einstellbar, Mindestabstand zwischen Stufen 7 Tage (harte Untergrenze im Code).

## Wann wird überhaupt vorgeschlagen

Ein Beleg bekommt einen Vorschlag nur, wenn **alle** Bedingungen gelten:

1. Status im Spiegel `offen` oder `ueberfaellig` und `offen > 0`.
2. Kontakt hat `kundentyp` gesetzt (sonst "Klärung nötig", Anforderung D3). Gepflegt in der Liste „Kundentyp festlegen“ (M1-10) durch Inhaber oder Freigeber, protokolliert; der Lexware-Hinweis Firma/Person wird nur angezeigt, nie übernommen. Belege ohne Kontakt (Sammelkunde) werden nie automatisch gemahnt.
3. Weder Beleg noch Kontakt pausiert.
4. Für diese Stufe existiert noch kein Vorschlag (eindeutig auf Beleg und Stufe).
5. Die vorige Stufe wurde versendet (Stufe 1 setzt versendete Stufe 0 voraus, außer Stufe 0 ist in der Firma deaktiviert).
6. Kontakt hat eine E-Mail-Adresse; sonst Vorschlag mit Hinweis "Postversand nötig" und ohne Versandknopf.

## Verzugsbeginn (§ 286 BGB)

Implementiere als reine Funktion `verzugsbeginn(beleg, kontakt, versaende) -> date | None` mit Tests für jede Zeile:

| Fall | Verzugsbeginn |
| --- | --- |
| Unternehmer, Rechnung zugegangen | Fälligkeit + 30 Tage (§ 286 Abs. 3). Zugang = Belegdatum + 3 Tage, solange kein besserer Nachweis existiert |
| Privatkunde, Rechnung enthielt Verzugshinweis (Firmeneinstellung `verzugshinweis_auf_rechnungen` oder Flag am Beleg) | Fälligkeit + 30 Tage |
| Privatkunde ohne Hinweis | Zugang der ersten Mahnung nach Fälligkeit (Abs. 1). Zugang = Versanddatum der Stufe 0 + 1 Tag |
| Unternehmer, Stufe 0 vor Ablauf der 30 Tage versendet | früheres Datum aus "Zugang Stufe 0 + 1 Tag" und "Fälligkeit + 30" |
| Fälligkeit fehlt im Bestandstool | kein Verzug berechenbar → keine Zinsen, keine Pauschale, Hinweis im Vorschlag |

Kalendermäßig bestimmte Zahlungstermine (§ 286 Abs. 2 Nr. 1) werden **nicht** automatisch angenommen, weil ein einseitig auf die Rechnung gedrucktes Datum dafür in der Regel nicht reicht.

**Umsetzung (M2-02, `dunning/recht.py`), Auslegungen zugunsten des Schuldners:**
- Die 30 Tage nach § 286 Abs. 3 laufen ab dem späteren Datum aus Fälligkeit und Zugang (Belegdatum + 3 Tage). Bei üblichen Zahlungszielen ist das die Fälligkeit, bei sofort fälligen Rechnungen der Zugang.
- Zeile 4 wird wörtlich gelesen: „Zugang Stufe 0 + 1 Tag“ = Versanddatum + 2 Tage (einen Tag später als Zeile 3).
- Beim Privatkunden mit Verzugshinweis zählt eine frühere Erinnerung nicht (die Tabelle nennt dafür keine Zeile).
- Ein Schreiben am Fälligkeitstag ist keine Mahnung „nach Fälligkeit“.
- Zinsen laufen ab dem Tag **nach** dem Verzugsbeginn bis einschließlich Stichtag (§ 187 Abs. 1 BGB entsprechend). Pauschale ebenfalls erst ab dem Folgetag.

## Verzugszinsen (§ 288 BGB)

- Satz: Basiszins + **5** Prozentpunkte bei Privatkunden, + **9** Prozentpunkte bei Unternehmern (Entgeltforderung).
- Berechnung taggenau auf den **offenen** Betrag (Teilzahlungen aus Lexware berücksichtigen), Zinstage = Kalendertage, Divisor 365 (366 in Schaltjahren). Bei Basiszinswechsel innerhalb des Zeitraums abschnittsweise rechnen.
- Zinsen werden in der Mahnung **ausgewiesen**, aber nicht auf die Rechnung gebucht.
- Zinsen unter 1,00 € werden nicht ausgewiesen.
- Firma kann Zinsen abschalten (viele Handwerker wollen Kunden nicht verärgern). Standard: Stufe 1 und 2 an, Stufe 0 immer aus.
- Umsetzung (M2-02): Abschnitte je Basiszins-Halbjahr und Kalenderjahr, jeder Abschnitt auf Cent gerundet (ROUND_HALF_UP), Summe der Abschnitte ist der ausgewiesene Betrag; die Zeilen erscheinen als Berechnungsgrundlage in Mail und Lexware-Mahnung. Teilzahlungen: Zinsen auf den aktuell offenen Betrag für den ganzen Zeitraum (nie mehr als geschuldet). Ein Basiszins gilt höchstens bis zum nächsten 1.1. bzw. 1.7.; ist der Folgewert nicht gepflegt, gibt es keine Zinsen und einen Hinweis.

### Basiszins-Tabelle (Startwerte, vor Go-live mit Bundesbank abgleichen)

| gültig ab | Satz |
| --- | --- |
| 2025-01-01 | 2,27 % |
| 2025-07-01 | 1,27 % |
| 2026-01-01 | 1,27 % |
| 2026-07-01 | 1,52 % |

Quelle für den aktuellen Wert: Bundesbank-Pressemitteilung vom 30.06.2026. Die Tabelle wird halbjährlich gepflegt (Ticket im Betriebshandbuch: Erinnerung am 1. Januar und 1. Juli). Fehlt ein Wert für ein Datum, werden **keine** Zinsen berechnet und der Inhaber gewarnt.

## Pauschale (§ 288 Abs. 5 BGB)

- 40 € **nur** bei Unternehmern und nur wenn Verzug besteht.
- Einmal je Forderung, nicht je Mahnstufe. Umsetzung: Die Pauschale steht in der ersten Mahnung, bei der Verzug besteht; spätere Stufen weisen sie nicht erneut aus (Hinweis im Vorschlag).
- Auch bei Abschlagsrechnungen zulässig.
- Bei Privatkunden **nie** eine Pauschale und keine pauschalen "Mahngebühren".

## Textvorgaben

- Stufe 0: Formulierung "Sicher ist das nur ein Versehen", kein Vorwurf.
- Jede Mahnung nennt: Rechnungsnummer, Rechnungsdatum, ursprüngliche Fälligkeit, offener Betrag, Zinsen und Pauschale getrennt mit Berechnungsgrundlage, neue Zahlungsfrist als Datum, Bankverbindung aus Lexware oder Firmendaten.
- "Falls sich Ihre Zahlung mit diesem Schreiben überschnitten hat, betrachten Sie es als gegenstandslos."
- Keine Drohung mit Schufa, Inkasso oder Rechtsanwalt im MVP.

## Freigabe und Versand

- Vorschläge entstehen täglich, Versand **nur** nach Freigabe durch Inhaber oder Freigeber (eingeloggt, 2FA).
- Freigabe einzeln oder als Sammelfreigabe "alle markierten".
- Vor dem Versand: Frische-Check im Bestandstool. Ist der Posten bezahlt oder der offene Betrag gesunken, Vorschlag verwerfen bzw. neu berechnen und erneut zur Freigabe stellen.
- Versand per E-Mail mit Absendername der Firma, Reply-To der Firma, PDF-Anhang. Kopie (BCC) an die Firma optional.
