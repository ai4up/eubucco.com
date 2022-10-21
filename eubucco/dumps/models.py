import uuid

from django.db import models


# Create your models here.
class Dump(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.ForeignKey("users.User", on_delete=models.DO_NOTHING)
    requested_on = models.DateTimeField(auto_now=True)
    name = models.CharField(max_length=30)
    countries = models.ManyToManyField("data.Country")
    regions = models.ManyToManyField("data.Region")
    cities = models.ManyToManyField("data.City")
    is_done = models.BooleanField(default=False)
    status = models.CharField(max_length=30)
    url = models.URLField(blank=True)
    is_deleted = models.BooleanField(default=False)
