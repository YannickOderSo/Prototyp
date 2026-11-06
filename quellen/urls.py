from django.urls import path

from . import views

app_name = "quellen"

urlpatterns = [
    path("", views.uebersicht, name="uebersicht"),
    path("adresse/", views.adresse, name="adresse"),
    path("kopie/<int:pk>/", views.kopie, name="kopie"),
    path("kontoauszug/", views.kontoauszug, name="kontoauszug"),
    path("zahlung/<int:pk>/", views.zahlung, name="zahlung"),
]
