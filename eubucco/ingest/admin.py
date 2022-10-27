from django.contrib import admin

from .models import IngestedGPKG


class IngestedGPKGAdmin(admin.ModelAdmin):
    ...


admin.site.register(IngestedGPKG, IngestedGPKGAdmin)
