from django.urls import path

from . import views

app_name = "dunning"

urlpatterns = [
    path("mahnplan/", views.mahnplan, name="mahnplan"),
]
