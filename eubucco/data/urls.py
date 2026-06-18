from django.urls import path
from django.shortcuts import redirect

from . import views

app_name = "data"
urlpatterns = [
    path("", lambda r: redirect("files:index"), name="index"),
    path("map", views.map, name="map"),
    path("explorer", views.explorer, name="explorer"),
    path("coverage", views.coverage, name="coverage"),
    path("conflation-demo", views.conflation, name="conflation"),
    path("webhook/minio/", views.minio_webhook, name="minio_webhook"),
]
