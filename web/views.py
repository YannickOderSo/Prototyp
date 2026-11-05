from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def start(request: HttpRequest) -> HttpResponse:
    return render(request, "web/start.html")
