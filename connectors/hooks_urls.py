from django.urls import path

from dunning.mailversand import zustellung_webhook

from . import webhooks

app_name = "hooks"

urlpatterns = [
    path("lexware/<str:token>/", webhooks.lexware, name="lexware"),
    path("zustellung/<str:token>/", zustellung_webhook, name="zustellung"),
]
