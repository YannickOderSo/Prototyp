from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

from .rechtstexte import rechtstext as finde_rechtstext


def start(request: HttpRequest) -> HttpResponse:
    return render(request, "web/start.html")


@login_not_required
def rechtstext(request: HttpRequest, slug: str) -> HttpResponse:
    text = finde_rechtstext(slug)
    if text is None:
        raise Http404
    return render(request, "web/rechtstext.html", {"text": text, "vorlage": f"web/rechtstexte/{text.slug}.html"})
