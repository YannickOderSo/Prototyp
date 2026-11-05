from django.urls import path

from . import views

app_name = "connectors"

urlpatterns = [
    path("lexware/", views.lexware, name="lexware"),
    path("lexware/trennen/", views.lexware_trennen, name="lexware_trennen"),
]
