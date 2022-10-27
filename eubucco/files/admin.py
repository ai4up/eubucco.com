from django.contrib import admin

from .models import File


class FileAdmin(admin.ModelAdmin):
    ...


admin.site.register(File, FileAdmin)
