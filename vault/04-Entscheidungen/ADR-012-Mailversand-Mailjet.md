# ADR-012: Plattform-Mailversand über Mailjet

Status: **vorgeschlagen** · 7. November 2026 · wartet auf Bestätigung durch Yannick und Lukas (Go-Live-Checkliste, Punkt „p0-mail“) · ergänzt ADR-005 und ADR-006

## Kontext
Belegfluss versendet Erinnerungen, Mahnungen, Angebots-Erinnerungen, Sammelmails und Systemmails im Namen der Betriebe (ADR-006). Ohne eigenes SMTP des Betriebs läuft das über ein Plattform-SMTP. Bisher war nur festgelegt: ein EU-Anbieter mit AVV (ADR-005, Offene-Fragen.md). Im Go-Live-Plan ist Mailjet Essential vorgesehen. Für spätere Zustellfehler (Bounce, Spam-Beschwerde) gibt es seit M2-06 den Webhook `/hooks/zustellung/<token>/`, bisher nur mit einem eigenen, generischen Format.

## Entscheidung (Vorschlag)
1. **Plattform-SMTP:** Mailjet über SMTP-Relay (`EMAIL_HOST`, Port 587, STARTTLS), Tarif Essential. Kein API-Versand, damit der Anbieter austauschbar bleibt.
2. **Zustellmeldungen:** Mailjet-Ereignisse (Event API) an `https://<domain>/hooks/zustellung/<ZUSTELLUNG_WEBHOOK_TOKEN>/`, Ereignisse „bounce“, „blocked“ und „spam“, gern gruppiert. Belegfluss setzt beim Versand über das Plattform-SMTP den Kopf `X-MJ-CustomID` auf die Message-ID; Mailjet gibt ihn im Ereignis als `CustomID` zurück. Zuordnung nur darüber, nie über die Empfängeradresse.
3. **Antwort 200:** Mailjet wiederholt jede andere Antwort 24 Stunden lang alle 30 Sekunden. Der Webhook bestätigt deshalb jede gültige Meldung mit 200, auch wenn sie keinem Versand zugeordnet werden kann.
4. **Schutz:** Mailjet signiert seine Aufrufe nicht. Geschützt wird über HTTPS und das geheime Token im Pfad (mindestens 32 zufällige Zeichen), dazu ein Ratenlimit.
5. **Betriebe mit eigenem SMTP** bekommen keinen Mailjet-Kopf; Zustellfehler sieht dort nur der Betrieb selbst (sofortige Ablehnungen erfasst Belegfluss weiterhin).
6. Umschalten über `MAILVERSAND_ANBIETER=mailjet`. Ein anderer Anbieter braucht nur einen weiteren kleinen Übersetzer im Webhook.

## Vor dem Bestätigen prüfen
- AVV mit Mailjet abschließen; Datenstandort EU und die Unterauftragsverarbeiter von Mailjet prüfen (Liste der Unterauftragsverarbeiter von Belegfluss ergänzen).
- SPF, DKIM und DMARC für die Absenderdomain bei Mailjet einrichten.
- Feldnamen mit einem echten Ereignis aus einem Testversand prüfen (Go-Live-Checkliste „p4-mail“). Gebaut ist nach den Beispielen der Mailjet-Doku, nicht gegen einen echten Aufruf.

## Folgen
+ Zustellfehler von Mahnungen und Angebots-Erinnerungen werden im Cockpit sichtbar, ohne dass der Betrieb in Mailjet nachsehen muss.
+ Anbieterwechsel bleibt einfach (SMTP, kleiner Übersetzer).
- Kein Schutz gegen gefälschte Meldungen außer dem Token: Wer das Token kennt, kann Zustellfehler eintragen (keine Außenwirkung, nur ein Hinweis im Cockpit; Token bei Verdacht wechseln).
