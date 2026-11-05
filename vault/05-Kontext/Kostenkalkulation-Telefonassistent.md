# Kostenkalkulation KI-Telefonassistent

Stand 5. November 2026 · alle Beträge netto · Grundlage: Preisrecherche vom selben Tag (Quellen unten). Die vollständige Rechnung mit Formeln liegt als Excel-Datei und PDF bei Yannick („Kostenkalkulation-Telefonassistent.xlsx/.pdf“). Schätzungen sind als solche gekennzeichnet. Entscheidung zur Technik: [[ADR-010-KI-Telefonassistent]].

## Ergebnis
| Kennzahl | Wert |
|---|---|
| Kosten je Anruf (2 Min., 5 Runden; Schätzung) | 1,36 ct (0,68 ct je Minute) |
| Variable Kosten je Betrieb und Monat (60 Anrufe) | 0,82 € |
| Höchstens je Betrieb (Limit 400 Gespräche, jedes an der Obergrenze) | 13,43 € |
| Fixkosten je Monat zum Start | 63,95 € (Hetzner AX41 59 € + easybell Business 10 4,95 €) |
| Kostendeckung bei 19 € je Betrieb | ab 4 Betrieben |
| Einmalig vor dem Start | 500 bis 1.345 € (Rufnummernblock, rechtliche Prüfung, Testanrufe) |

Rechenweg je Anruf (Variante 1):
- Spracherkennung: 2,0 Min. × 0,0035 $ ÷ 1,1224 = 0,0062 €
- KI-Dialog: 5 × (1.500 × 0,11 $ + 120 × 0,55 $) ÷ 1 Mio. ÷ 1,1224 = 0,0010 €
- Sprachausgabe: 5 × 110 Zeichen × 13 $ ÷ 1 Mio. ÷ 1,1224 = 0,0064 €
- Telefonie eingehend: 0 € (Annahme, nicht verifiziert)

## Varianten
| Variante | je Anruf | je Betrieb/Monat |
|---|---|---|
| 1 Empfehlung: Voxtral Batch · Haiku 5.5 · Voxtral TTS | 1,36 ct | 0,82 € |
| 2 Voxtral Batch · Haiku 5.5 · Azure TTS (Germany West Central) | 1,47 ct | 0,89 € |
| 3 Voxtral Batch · Haiku 5.5 · Piper (nur mit freigegebener Stimme) | 0,73 ct | 0,44 € |
| 4 Voxtral Realtime · Sonnet 5.5 · Voxtral TTS | 5,59 ct | 3,36 € |

## Abos und Verträge
- **Telefonie:** easybell SIP-Trunk Business 10, 4,95 €/Monat, ohne Mindestlaufzeit; 100er-Rufnummernblock 49,95 € einmalig im Ortsnetz unseres Sitzes (eine Nummer je Betrieb). Ab mehr als 10 gleichzeitigen Gesprächen Business 50 (19,95 €).
- **Server:** Hetzner AX41 in Falkenstein, 59 €/Monat, ohne Einrichtung und Mindestlaufzeit (Hetzner Cloud ist derzeit nicht bestellbar). Ab ca. 30 gleichzeitigen Gesprächen AX42 (Schätzung, Lasttest).
- **Sprache:** Mistral AI nach Verbrauch (Voxtral Transcribe, Voxtral TTS 3), AVV abschließen, Ausgabenlimit setzen.
- **KI:** Amazon Bedrock eu-central-1, Claude Haiku 5.5 im EU-Profil, nach Verbrauch, Budget-Alarm.
- **Nicht:** Telekom CompanyFlex (Standortbindung, 2 Jahre, schließt TK-Anbieter aus), Twilio/Vapi/Retell (USA), ElevenLabs (EU nur Enterprise), sipgate trunking (Konkurrent sona), Piper-„thorsten“ (Lizenz).

## Preis (Vorschlag, offen)
19 € netto im Monat mit 150 Inklusivminuten, danach 9 ct je Minute. Vergleich: sipgate sona Free 0 € (500 Min., Umfang nicht geprüft), Starter 69,95 € (1.000 Min.); fonio.ai Solo 99 € (Twilio, USA); Placetel AI Grow 69 € (750 Min.); IONOS Flex 39 € brutto (30 Anrufe). Markt ca. 7 bis 15 ct je Minute. Bei 50 Betrieben bleiben rund 845 € im Monat vor Personal.

## Hinweise
- Die Rufumleitung bezahlt der Betrieb über seinen eigenen Anschluss; in Festnetz-Flatrates meist enthalten (Telekom-Preisliste geprüft).
- Ortsnetznummern nur im Ortsnetz unseres Sitzes (BNetzA-Verfügung 25/2006).
- Offene Punkte stehen in [[Offene-Fragen]].

## Quellen (abgerufen am 5. November 2026)
easybell.de/preisliste-business · placetel.de · sipgate.de (trunking, preise, ai-agents) · peoplefone.com · Telekom CompanyFlex Flyer 01/2026 · bundesnetzagentur.de Vfg. 25/2006 · telekom.de/agb/downloads/55828.pdf · docs.mistral.ai/inference/pricing · docs.mistral.ai/studio/audio · AWS Price List eu-central-1 (12.10.2026) · AWS Model Cards Haiku 5.5/Sonnet 5.5 · huggingface.co/rhasspy/piper-voices (Model Card thorsten) · lessac-Lizenz cstr.ed.ac.uk · prices.azure.com · elevenlabs.io · hetzner.com · fonio.ai/preise · placetel.de/placetel-ai-preise · ionos.de · ecb.europa.eu
