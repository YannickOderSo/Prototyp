from django.urls import path

from . import views

app_name = "capture"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("neu/", views.neu, name="neu"),
    path("postfach/", views.postfach, name="postfach"),
    path("hochladen/", views.hochladen, name="hochladen"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/neuversuch/", views.neuversuch, name="neuversuch"),
    path("<int:pk>/transkript/", views.transkript, name="transkript"),
    path("<int:pk>/pruefen/", views.pruefen, name="pruefen"),
    path("<int:pk>/verwerfen/", views.verwerfen, name="verwerfen"),
    path("<int:pk>/freigeben/", views.freigeben, name="freigeben"),
    path("<int:pk>/positionsliste/", views.positionsliste, name="positionsliste"),
    path("<int:pk>/positionsliste.csv", views.positionsliste_csv, name="positionsliste_csv"),
]
