import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


# Create your models here.
class FileType(models.TextChoices):
    BUILDING = "BE", _("building")
    EXAMPLE = "EX", _("example")
    ADDITIONAL = "AD", _("additional")

    def __str__(self):
        return self.name


class File(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=100)
    ingested_on = models.DateTimeField(auto_now_add=True)
    size_in_mb = models.FloatField()
    path = models.FilePathField(max_length=200, unique=True)
    type = models.CharField(max_length=2, choices=FileType.choices, db_index=True)

    def __str__(self):
        return self.name
