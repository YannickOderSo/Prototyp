from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django import template

register = template.Library()


@register.filter
def euro(wert: object) -> str:
    """1234.5 → „1.234,50 €“ (ohne float)."""
    if wert is None or wert == "":
        return "–"
    betrag = Decimal(str(wert)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    text = f"{betrag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"


@register.filter
def datum(wert: date | None) -> str:
    return wert.strftime("%d.%m.%Y") if wert else "–"


@register.filter
def tage_seit(wert: date | None, heute: date) -> int | None:
    return (heute - wert).days if wert else None


@register.filter
def zahl(wert: object) -> str:
    if wert is None:
        return "–"
    return str(wert).replace(".", ",")
