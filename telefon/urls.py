from django.urls import path

from . import views

app_name = "telefon"

urlpatterns = [
    path("", views.rueckrufe, name="rueckrufe"),
    path("<int:pk>/", views.rueckruf, name="rueckruf"),
    path("<int:pk>/erledigt/", views.erledigt, name="erledigt"),
    path("einstellungen/", views.einstellungen, name="einstellungen"),
    path("test/", views.testanruf, name="testanruf"),
    path("test/start/", views.test_start, name="test_start"),
    path("test/<str:kennung>/nachricht/", views.test_nachricht, name="test_nachricht"),
    path("test/<str:kennung>/ende/", views.test_ende, name="test_ende"),
    path("asterisk/anruf/", views.asterisk_anruf, name="asterisk_anruf"),
]
