"""Minimaler Cron-Ausdruck (Minute Stunde Tag Monat Wochentag), ausgewertet in lokaler Zeit."""

from datetime import datetime, timedelta

_BEREICHE = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]


def _feld(text: str, unten: int, oben: int) -> frozenset[int]:
    werte: set[int] = set()
    for teil in text.split(","):
        schritt = 1
        if "/" in teil:
            teil, schritt_text = teil.split("/", 1)
            schritt = int(schritt_text)
            if schritt < 1:
                raise ValueError("Schrittweite muss mindestens 1 sein")
        if teil == "*":
            von, bis = unten, oben
        elif "-" in teil:
            a, b = teil.split("-", 1)
            von, bis = int(a), int(b)
        else:
            von = bis = int(teil)
        if von < unten or bis > oben or von > bis:
            raise ValueError(f"Wert außerhalb von {unten}-{oben}: {text}")
        werte.update(range(von, bis + 1, schritt))
    return frozenset(werte)


class Cron:
    def __init__(self, ausdruck: str) -> None:
        felder = ausdruck.split()
        if len(felder) != 5:
            raise ValueError(f"Cron-Ausdruck braucht 5 Felder: {ausdruck!r}")
        # Wochentag: 0 = Sonntag (wie cron), 7 ebenfalls Sonntag
        felder[4] = felder[4].replace("7", "0")
        self.ausdruck = ausdruck
        self.minuten, self.stunden, self.tage, self.monate, self.wochentage = (
            _feld(f, u, o) for f, (u, o) in zip(felder, _BEREICHE, strict=True)
        )

    def passt(self, zeit: datetime) -> bool:
        return (
            zeit.minute in self.minuten
            and zeit.hour in self.stunden
            and zeit.day in self.tage
            and zeit.month in self.monate
            and (zeit.isoweekday() % 7) in self.wochentage
        )

    def naechster(self, nach: datetime) -> datetime:
        """Erster passender Zeitpunkt (minutengenau) strikt nach `nach`. Arbeitet mit naiver lokaler Zeit."""
        zeit = nach.replace(second=0, microsecond=0) + timedelta(minutes=1)
        grenze = zeit + timedelta(days=366 * 5)
        while zeit < grenze:
            if zeit.month not in self.monate:
                zeit = (zeit.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
                continue
            if zeit.day not in self.tage or (zeit.isoweekday() % 7) not in self.wochentage:
                zeit = zeit.replace(hour=0, minute=0) + timedelta(days=1)
                continue
            if zeit.hour not in self.stunden:
                zeit = zeit.replace(minute=0) + timedelta(hours=1)
                continue
            if zeit.minute not in self.minuten:
                zeit += timedelta(minutes=1)
                continue
            return zeit
        raise ValueError(f"Kein Termin für {self.ausdruck!r} gefunden")
