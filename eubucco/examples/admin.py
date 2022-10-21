from django.contrib import admin

from .models import Example

# Register your models here.


class ExampleAdmin(admin.ModelAdmin):
    ...


admin.site.register(Example, ExampleAdmin)
