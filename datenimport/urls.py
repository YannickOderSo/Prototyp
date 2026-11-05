from django.urls import path

from . import views

app_name = "datenimport"

urlpatterns = [
    path("", views.uebersicht, name="uebersicht"),
    path("vorlage/<slug:art>.<slug:format>", views.vorlage, name="vorlage"),
    path("<int:pk>/", views.vorgang, name="vorgang"),
    path("<int:pk>/zuordnung/", views.zuordnung, name="zuordnung"),
    path("<int:pk>/freigeben/", views.freigeben, name="freigeben"),
    path("<int:pk>/verwerfen/", views.verwerfen, name="verwerfen"),
    path("<int:pk>/fortsetzen/", views.fortsetzen, name="fortsetzen"),
    path("beleg/<int:pk>/zahlung/", views.zahlung, name="zahlung"),
]
