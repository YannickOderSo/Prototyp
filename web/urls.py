from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.start, name="start"),
    path("einstellungen/", views.einstellungen, name="einstellungen"),
    path("einrichtung/", views.einrichtung, name="einrichtung"),
    path("rechtliches/<slug:slug>/", views.rechtstext, name="rechtstext"),
]
