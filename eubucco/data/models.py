from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _


# Create your models here.
class BuildingType(models.TextChoices):
    RESIDENTIAL = "RE", _("residential")
    NON_RESIDENTIAL = "NR", _("non − residential")
    UNKNOWN = "UN", _("unknown")


class Country(models.Model):
    name = models.CharField(max_length=57, unique=True)
    geometry = models.GeometryField(srid=3035, null=True)
    convex_hull = models.GeometryField(srid=3035, null=True)
    csv_path = models.FilePathField(null=True)
    csv_size_in_mb = models.FloatField(null=True)
    gpkg_path = models.FilePathField(null=True)
    gpkg_size_in_mb = models.FloatField(null=True)

    def __str__(self):
        return self.name


class Region(models.Model):
    name = models.CharField(max_length=60)
    in_country = models.ForeignKey(Country, on_delete=models.CASCADE)
    geometry = models.GeometryField(srid=3035, null=True)

    class Meta:
        unique_together = ("name", "in_country")

    def __str__(self):
        return self.name


class City(models.Model):
    name = models.CharField(max_length=60)
    in_country = models.ForeignKey(Country, on_delete=models.CASCADE)
    in_region = models.ForeignKey(Region, on_delete=models.CASCADE)
    geometry = models.GeometryField(srid=3035, null=True)

    class Meta:
        unique_together = ("name", "in_region")

    def __str__(self):
        return self.name


class Building(models.Model):
    id = models.CharField(max_length=50, primary_key=True)
    id_source = models.CharField(max_length=80)
    country = models.ForeignKey(
        Country, on_delete=models.CASCADE, db_index=True, null=True
    )
    region = models.ForeignKey(
        Region, on_delete=models.CASCADE, db_index=True, null=True
    )
    city = models.ForeignKey(City, on_delete=models.CASCADE, db_index=True, null=True)
    height = models.FloatField(null=True)
    age = models.IntegerField(null=True)
    type = models.CharField(
        max_length=2,
        choices=BuildingType.choices,
        default=BuildingType.UNKNOWN,
    )
    type_source = models.CharField(max_length=70)
    geometry = models.GeometryField(srid=3035)

    def __str__(self):
        return self.id

    class Meta:
        indexes = [
            models.Index(
                fields=[
                    "country",
                ]
            ),
            models.Index(
                fields=[
                    "region",
                ]
            ),
            models.Index(
                fields=[
                    "city",
                ]
            ),
        ]
