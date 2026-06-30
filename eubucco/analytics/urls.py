from django.urls import path

from . import views

app_name = "analytics"
urlpatterns = [
    path("webhook/minio/", views.minio_webhook, name="minio_webhook"),
]
