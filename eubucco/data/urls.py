from django.urls import path
from django.shortcuts import redirect

from . import views

app_name = "data"
urlpatterns = [
    path("", lambda r: redirect("data:download", version="v0.2"), name="index"),
    path("<str:version>", views.data_versioned, name="download"),
    path("map", views.map, name="map"),
]
