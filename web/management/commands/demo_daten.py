"""Demo-Daten zum Ansehen der Oberfläche auf localhost (nur mit DJANGO_DEBUG=true).

Legt eine Demo-Firma mit Inhaber, gespiegelten Kunden, Artikeln und Rechnungen in allen Altersstufen an,
erzeugt die heutigen Mahnvorschläge und zwei Erfassungen in der Prüfansicht (Rechnung mit fehlendem Preis,
Angebot). Es wird nichts an Lexware, Mistral oder Bedrock gesendet: Die Lexware-Verbindung nutzt den
Demo-Connector (connectors/demo.py), der nur auf der eigenen Datenbank arbeitet. Freigegebene Mahnungen
gehen an das eingestellte Mail-Backend (lokal Mailpit).

Beim ersten Anmelden richtet der Demo-Nutzer die Zwei-Faktor-Anmeldung ein (Authenticator-App), wie im
echten Betrieb.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Firma, Mitgliedschaft, Nutzer, Rolle
from capture.entwurf import regeln_anwenden
from capture.models import Erfassung
from cockpit.krypto import verschluesseln
from connectors.demo import DEMO_ORGANISATION
from connectors.models import Verbindung
from dunning.models import Mahnplan, Mahnvorschlag
from dunning.vorschlaege import vorschlagslauf
from ledger.models import Artikel, Beleg, Kontakt

FIRMA = "Malerbetrieb Muster GmbH (Demo)"
EMAIL = "demo@cockpit.local"
PASSWORT = "Demo-Cockpit-2026!"
D = Decimal

KUNDEN = [
    # extern_id, Name, E-Mail, Kundentyp, Firma laut Lexware
    ("k-bau", "Bau AG", "buchhaltung@bau-ag.example", "unternehmer", True),
    ("k-huber", "Huber Hausverwaltung GmbH", "rechnung@huber-hv.example", "unternehmer", True),
    ("k-erika", "Erika Musterfrau", "erika@example.org", "privat", False),
    ("k-praxis", "Praxis Dr. Sommer", "praxis@sommer.example", "unternehmer", True),
    ("k-weber", "Familie Weber", "weber@example.org", "unbekannt", False),
    ("k-kita", "Kita Sonnenschein e. V.", "verwaltung@kita.example", "unternehmer", True),
]

# Nummer, Kunde, Brutto, offen, Tage seit Fälligkeit (negativ = noch nicht fällig)
RECHNUNGEN = [
    ("RE2026-101", "k-bau", "4760.00", "4760.00", 45),
    ("RE2026-108", "k-huber", "1904.00", "1904.00", 24),
    ("RE2026-112", "k-erika", "833.00", "833.00", 12),
    ("RE2026-115", "k-praxis", "2618.00", "1309.00", 9),
    ("RE2026-117", "k-weber", "595.00", "595.00", 15),
    ("RE2026-119", "k-kita", "3451.00", "3451.00", 3),
    ("RE2026-121", "k-bau", "7140.00", "7140.00", -5),
    ("RE2026-122", "k-huber", "1071.00", "1071.00", -12),
    ("RE2026-124", "k-erika", "476.00", "476.00", -20),
]

ARTIKEL = [
    ("art-maler-stunde", "Malerarbeiten Facharbeiter", "Stunde", "58.00", "19", "SERVICE"),
    ("art-helfer-stunde", "Helfer", "Stunde", "42.00", "19", "SERVICE"),
    ("art-dispersion", "Dispersionsfarbe weiß, 12,5 l", "Eimer", "64.90", "19", "PRODUCT"),
    ("art-abdeckung", "Abdeckmaterial pauschal", "pauschal", "35.00", "19", "PRODUCT"),
    ("art-anfahrt", "Anfahrt", "pauschal", "25.00", "19", "SERVICE"),
]


class Command(BaseCommand):
    help = "Legt Demo-Daten für die lokale Ansicht an (nur mit DJANGO_DEBUG=true)."

    def handle(self, *args: Any, **optionen: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("Demo-Daten nur in der lokalen Entwicklung (DJANGO_DEBUG=true).")
        if Firma.objects.filter(name=FIRMA).exists():
            raise CommandError(
                "Demo-Firma existiert bereits. Für einen frischen Stand die Demo-Datenbank neu anlegen "
                "(das Protokoll ist unveränderlich und lässt sich nicht leeren)."
            )
        with transaction.atomic():
            self._anlegen()
        self.stdout.write(
            f"Demo bereit. Anmeldung: {EMAIL} / {PASSWORT}\n"
            "Beim ersten Anmelden die Zwei-Faktor-Anmeldung mit einer Authenticator-App einrichten."
        )

    def _anlegen(self) -> None:
        heute = timezone.localdate()
        firma = Firma.objects.create(
            name=FIRMA,
            strasse="Musterweg 1",
            plz="12345",
            ort="Musterstadt",
            email_absender="Malerbetrieb Muster",
            reply_to="buero@muster.example",
            bankverbindung="IBAN DE12 3456 7890 1234 5678 90, Musterbank",
            mahn_signatur="Max Muster\nMalerbetrieb Muster GmbH · Musterweg 1 · 12345 Musterstadt",
        )
        nutzer = Nutzer.objects.filter(email=EMAIL).first() or Nutzer.objects.create_user(
            email=EMAIL, password=PASSWORT, name="Max Muster"
        )
        Mitgliedschaft.objects.create(nutzer=nutzer, firma=firma, rolle=Rolle.INHABER)
        jetzt = timezone.now()
        Verbindung.objects.create(
            firma=firma,
            schluessel_verschluesselt=verschluesseln("demo-kein-echter-schluessel"),
            firmenname_extern="Malerbetrieb Muster GmbH",
            organisation_id=DEMO_ORGANISATION,
            erstimport_fertig=jetzt,
            letzter_abgleich=jetzt,
        )
        Mahnplan.objects.create(firma=firma)
        kunden = {}
        for extern_id, name, email, typ, ist_firma in KUNDEN:
            kunden[extern_id] = Kontakt.objects.create(
                firma=firma,
                extern_id=extern_id,
                name=name,
                email=email,
                kundentyp=typ,
                ist_unternehmen_extern=ist_firma,
            )
        for extern_id, bezeichnung, einheit, netto, satz, typ in ARTIKEL:
            Artikel.objects.create(
                firma=firma,
                extern_id=extern_id,
                bezeichnung=bezeichnung,
                einheit=einheit,
                netto=D(netto),
                steuersatz=D(satz),
                typ=typ,
            )
        for nummer, kunde, brutto, offen, tage in RECHNUNGEN:
            faellig = heute - timedelta(days=tage)
            Beleg.objects.create(
                firma=firma,
                extern_id=f"demo-{nummer}",
                nummer=nummer,
                kontakt=kunden[kunde],
                kontakt_name=kunden[kunde].name,
                belegdatum=faellig - timedelta(days=14),
                faellig_am=faellig,
                brutto=D(brutto),
                offen=D(offen),
                status=Beleg.Status.UEBERFAELLIG if tage > 0 else Beleg.Status.OFFEN,
            )
        # Bezahlte Rechnungen der letzten Monate: Zahlungsdauer je Kunde und Prognose
        for i, (kunde, tage_bis_zahlung) in enumerate(
            [("k-bau", 34), ("k-bau", 41), ("k-huber", 18), ("k-erika", 9), ("k-praxis", 22), ("k-kita", 27)]
        ):
            belegdatum = heute - timedelta(days=60 + 25 * i)
            Beleg.objects.create(
                firma=firma,
                extern_id=f"demo-bezahlt-{i}",
                nummer=f"RE2026-0{40 + i}",
                kontakt=kunden[kunde],
                kontakt_name=kunden[kunde].name,
                belegdatum=belegdatum,
                faellig_am=belegdatum + timedelta(days=14),
                brutto=D("1190.00"),
                offen=D("0.00"),
                status=Beleg.Status.BEZAHLT,
                bezahlt_am=belegdatum + timedelta(days=tage_bis_zahlung),
            )
        # Die Bau AG wurde vor 20 Tagen erinnert: heute wäre die 1. Mahnung mit Zinsen und Pauschale dran
        erste = Beleg.objects.get(firma=firma, nummer="RE2026-101")
        Mahnvorschlag.objects.create(
            firma=firma,
            beleg=erste,
            stufe=0,
            status=Mahnvorschlag.Status.VERSENDET,
            versendet_am=jetzt - timedelta(days=20),
            offen_betrag=erste.offen,
            gesamt=erste.offen,
            freigegeben_von=nutzer,
            freigegeben_am=jetzt - timedelta(days=20),
        )
        vorschlagslauf(firma, heute)
        # Eine Erfassung (Sprachmemo) wartet in der Prüfansicht; Preise kommen aus den Artikeln
        erfassung = Erfassung.objects.create(
            firma=firma,
            erstellt_von=nutzer,
            kanal=Erfassung.Kanal.AUFNAHME,
            status=Erfassung.Status.PRUEFUNG,
            transkript=(
                "Rechnung für die Bau AG, Treppenhaus Musterstraße 5 gestrichen vom 2. bis 4. November. "
                "Zwölf Stunden Facharbeiter, sechs Stunden Helfer, drei Eimer Dispersionsfarbe, Abdeckmaterial "
                "und Anfahrt. Die Sockelleiste extra lackiert, Preis weiß ich gerade nicht."
            ),
            ki_ergebnis={
                "belegart": "rechnung",
                "kunde": "Bau AG",
                "angebot_nummer": "",
                "leistung_von": (heute - timedelta(days=3)).isoformat(),
                "leistung_bis": (heute - timedelta(days=1)).isoformat(),
                "positionen": [
                    _pos("art-maler-stunde", "Malerarbeiten Treppenhaus", 12, "Stunde"),
                    _pos("art-helfer-stunde", "Helfer", 6, "Stunde"),
                    _pos("art-dispersion", "Dispersionsfarbe weiß", 3, "Eimer"),
                    _pos("art-abdeckung", "Abdeckmaterial", 1, "pauschal"),
                    _pos("art-anfahrt", "Anfahrt", 1, "pauschal"),
                    _pos("", "Sockelleiste lackieren", 1, "pauschal"),
                ],
                "offene_fragen": ["Preis für das Lackieren der Sockelleiste fehlt."],
            },
        )
        regeln_anwenden(erfassung)
        # Ein Angebot aus einem Sprachmemo, vollständig zugeordnet und freigabebereit
        angebot = Erfassung.objects.create(
            firma=firma,
            erstellt_von=nutzer,
            kanal=Erfassung.Kanal.AUFNAHME,
            status=Erfassung.Status.PRUEFUNG,
            transkript=(
                "Angebot für Praxis Dr. Sommer: Wartezimmer und Flur streichen, etwa 85 Quadratmeter. "
                "Zwei Facharbeiter für zwei Tage, also 32 Stunden, vier Eimer Dispersionsfarbe weiß, "
                "Abdeckmaterial und zweimal Anfahrt. Farbton im Flur noch mit der Praxis abstimmen."
            ),
            ki_ergebnis={
                "belegart": "angebot",
                "kunde": "Praxis Dr. Sommer",
                "angebot_nummer": "",
                "leistung_von": "",
                "leistung_bis": "",
                "positionen": [
                    _pos("art-maler-stunde", "Wartezimmer und Flur streichen, ca. 85 m²", 32, "Stunde"),
                    _pos("art-dispersion", "Dispersionsfarbe weiß", 4, "Eimer"),
                    _pos("art-abdeckung", "Abdeckmaterial", 1, "pauschal"),
                    _pos("art-anfahrt", "Anfahrt", 2, "pauschal"),
                ],
                "offene_fragen": ["Farbton im Flur mit der Praxis abstimmen."],
            },
        )
        regeln_anwenden(angebot)


def _pos(artikel_id: str, beschreibung: str, menge: int, einheit: str) -> dict[str, object]:
    return {
        "artikel_id": artikel_id,
        "beschreibung": beschreibung,
        "menge": menge,
        "einheit": einheit,
        "quelle": "Sprachmemo",
        "herkunft": "gesprochen",
    }
