from django.shortcuts import redirect
from django.urls import path

from . import views

app_name = "data"
urlpatterns = [
    path("", lambda r: redirect("data:download"), name="index"),
    path("download", views.download, name="download"),
    path("download/<str:version>", views.download_version, name="download_version"),
]
