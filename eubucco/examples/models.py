from django.db import models


# Create your models here.
class Example(models.Model):
    name = models.CharField(max_length=30, primary_key=True)
    csv_path = models.FilePathField()
    csv_size_in_mb = models.FloatField()
    gpkg_path = models.FilePathField()
    gpkg_size_in_mb = models.FloatField()

    def __str__(self):
        return self.name
