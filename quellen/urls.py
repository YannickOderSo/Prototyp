from django.urls import path

from . import views

app_name = "quellen"

urlpatterns = [
    path("", views.uebersicht, name="uebersicht"),
    path("adresse/", views.adresse, name="adresse"),
    path("kopie/<int:pk>/", views.kopie, name="kopie"),
]
