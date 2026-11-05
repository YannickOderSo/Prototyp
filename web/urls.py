from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.start, name="start"),
    path("rechtliches/<slug:slug>/", views.rechtstext, name="rechtstext"),
]
