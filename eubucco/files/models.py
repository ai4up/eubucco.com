import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from eubucco.utils.version_enum import VersionEnum


# Create your models here.
class FileType(models.TextChoices):
    BUILDING = "BU", _("building")
    EXAMPLE = "EX", _("example")
    ADDITIONAL = "AD", _("additional")


class File(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=100)
    ingested_on = models.DateTimeField(auto_now_add=True)
    size_in_mb = models.FloatField()
    path = models.FilePathField(max_length=200, unique=True)
    type = models.CharField(max_length=2, choices=FileType.choices, db_index=True)
    info = models.CharField(max_length=200, null=False, blank=True)
    version = models.IntegerField(choices=VersionEnum.choices, null=False)

    def __str__(self):
        return self.name
