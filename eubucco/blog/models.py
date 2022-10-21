from django.db import models
from martor.models import MartorField


class Post(models.Model):
    title = models.CharField(max_length=60)
    slug = models.SlugField(max_length=30, unique=True, db_index=True)
    created_on = models.DateTimeField(auto_now_add=True)
    summary = models.TextField(max_length=600)
    text = MartorField()

    def __str__(self):
        return self.title

    class Meta:
        ordering = ["-created_on"]
