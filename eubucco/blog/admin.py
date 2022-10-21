from django.contrib import admin

from .models import Post


class BlogAdmin(admin.ModelAdmin):
    ...


admin.site.register(Post, BlogAdmin)
