from django.urls import path

from . import views

app_name = "dunning"

urlpatterns = [
    path("", views.freigabe, name="freigabe"),
    path("freigeben/", views.freigeben, name="freigeben"),
    path("<int:pk>/vorschau/", views.vorschau, name="vorschau"),
    path("<int:pk>/verwerfen/", views.verwerfen, name="verwerfen"),
    path("<int:pk>/neuversuch/", views.neuversuch, name="neuversuch"),
    path("<int:pk>/pdf/", views.pdf, name="pdf"),
    path("<int:pk>/post-versendet/", views.post_versendet, name="post_versendet"),
    path("mahnplan/", views.mahnplan, name="mahnplan"),
]
