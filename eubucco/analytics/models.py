from django.db import models

from eubucco.files.models import File


class FileDownload(models.Model):
    file = models.ForeignKey(File, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_api = models.BooleanField()

    def __str__(self):
        return str(self.file.id)
