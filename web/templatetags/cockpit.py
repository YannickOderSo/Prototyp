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
def euro_rund(wert: object) -> str:
    """1234.5 → „1.235 €“ für Beschriftungen in Diagrammen (gerundet, ohne float)."""
    if wert is None or wert == "":
        return "–"
    betrag = Decimal(str(wert)).quantize(Decimal("1"), ROUND_HALF_UP)
    return f"{betrag:,.0f}".replace(",", ".") + " €"


@register.filter
def hoehe(wert: object, hoechster: object) -> int:
    """Säulenhöhe in Fünferschritten (0 bis 100) relativ zum größten Wert; kleine Werte bleiben sichtbar."""
    try:
        w, h = Decimal(str(wert or 0)), Decimal(str(hoechster or 0))
    except ArithmeticError:
        return 0
    if w <= 0 or h <= 0:
        return 0
    stufe = int((w * 20 / h).quantize(Decimal("1"), ROUND_HALF_UP)) * 5
    return max(5, min(100, stufe))


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


@register.simple_tag
def icon(name: str, klasse: str = "") -> str:
    """Inline-SVG aus web/icons.py, für Screenreader verborgen (die Beschriftung steht daneben)."""
    from django.utils.html import format_html
    from django.utils.safestring import mark_safe

    from web.icons import ICONS

    pfade = ICONS.get(name)
    if pfade is None:
        return ""
    return format_html(
        '<svg class="icon {}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true" focusable="false">{}</svg>',
        klasse,
        mark_safe(pfade),  # noqa: S308 – feste Pfade aus web/icons.py, keine Nutzereingabe
    )


@register.simple_tag
def avatar(nutzer: object, groesse: str = "") -> str:
    """Rundes Avatar-Symbol eines Teammitglieds (I5). Für Screenreader verborgen; der Name steht daneben."""
    from django.utils.html import format_html

    if nutzer is None or not hasattr(nutzer, "avatar"):
        return ""
    symbol, farbe = nutzer.avatar
    return format_html(
        '<span class="avatar avatar-farbe-{} {}" aria-hidden="true">{}</span>', farbe, groesse, icon(symbol)
    )
