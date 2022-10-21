from django.apps import AppConfig


class BlogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "eubucco.blog"

    def ready(self):
        import eubucco.blog.signals  # noqa
