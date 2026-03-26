from django.urls import path
from django.shortcuts import redirect

from . import views

app_name = "data"
urlpatterns = [
    path("", lambda r: redirect("files:index"), name="index"),
    path("map", views.map, name="map"),
    path("webhook/minio/", views.minio_webhook, name="minio_webhook"),
]
