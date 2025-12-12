from django.urls import path

from . import views

app_name = "data"
urlpatterns = [
    path("map", views.map, name="map"),
]
