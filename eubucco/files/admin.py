from django.contrib import admin

from .models import File


class FileAdmin(admin.ModelAdmin):
    exclude = ("path",)


admin.site.register(File, FileAdmin)
