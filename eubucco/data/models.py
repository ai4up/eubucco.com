from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

# Create your models here.
from eubucco.files.models import File


class BuildingType(models.TextChoices):
    RESIDENTIAL = "RE", _("residential")
    NON_RESIDENTIAL = "NR", _("non − residential")
    UNKNOWN = "UN", _("unknown")


class Country(models.Model):
    name = models.CharField(max_length=57, unique=True)
    geometry = models.GeometryField(srid=3035, null=True)
    convex_hull = models.GeometryField(srid=3035, null=True)
    csv = models.ForeignKey(
        File, on_delete=models.DO_NOTHING, blank=True, null=True, related_name="+"
    )
    gpkg = models.ForeignKey(
        File, on_delete=models.DO_NOTHING, blank=True, null=True, related_name="+"
    )

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
    name = models.CharField(max_length=100)
    in_country = models.ForeignKey(Country, on_delete=models.CASCADE)
    in_region = models.ForeignKey(Region, on_delete=models.CASCADE)
    geometry = models.GeometryField(srid=3035, null=True)

    class Meta:
        unique_together = ("name", "in_region")

    def __str__(self):
        return self.name


class VersionEnum(models.IntegerChoices):
    V01 = 1, _("v0.1")
    VMSFT24 = 2, _("msft24")

    def version_from_path(self, path):
        version_string = path.split("-")[0]
        if version_string == "v0_1":
            return self.V01
        elif version_string == "vmsft24":
            return self.VMSFT24
        else:
            raise ValueError(f"Unknown version {version_string}")


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
    type_source = models.CharField(max_length=150)
    geometry = models.GeometryField(srid=3035)
    version = models.IntegerField(choices=VersionEnum.choices, null=False)

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
