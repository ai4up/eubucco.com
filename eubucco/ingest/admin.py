from django.contrib import admin

from .models import IngestedCsv


class IngestedCsvAdmin(admin.ModelAdmin):
    ...


admin.site.register(IngestedCsv, IngestedCsvAdmin)
