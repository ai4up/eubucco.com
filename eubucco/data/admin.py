from django.contrib import admin
from django.contrib.gis.admin import OSMGeoAdmin
from leaflet.admin import LeafletGeoAdmin

from .models import Building, City, Country, Region

# Register your models here.


@admin.register(Building)
class BuildingAdmin(OSMGeoAdmin):
    show_full_result_count = False
    list_display = (
        "id",
        "id_source",
        "height",
        "age",
        "type",
        "type_source",
        "geometry",
    )
    search_fields = ["id", "age", "type"]


@admin.register(Country)
class CountryAdmin(LeafletGeoAdmin):
    pass


@admin.register(Region)
class RegionAdmin(OSMGeoAdmin):
    pass


@admin.register(City)
class CityAdmin(OSMGeoAdmin):
    pass
