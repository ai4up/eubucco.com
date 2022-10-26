from django.db import models


# Create your models here.
class IngestedGPKG(models.Model):
    name = models.CharField(max_length=100)
    ingested_on = models.DateTimeField(auto_now_add=True)
    size_in_mb = models.FloatField()
    ingestion_time_in_s = models.FloatField()

    def __str__(self):
        return self.name
