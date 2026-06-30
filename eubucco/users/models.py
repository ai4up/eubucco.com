from django.contrib.auth.models import AbstractUser
from django.db.models import CharField
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """Minimal custom user model for eubucco.

    Public signup/login was removed; this exists so Django admin (the only
    authenticated surface) keeps a stable, swappable AUTH_USER_MODEL.
    """

    #: First and last name do not cover name patterns around the globe
    name = CharField(_("Name of User"), blank=True, max_length=255)
    first_name = None  # type: ignore
    last_name = None  # type: ignore

    def __str__(self):
        return self.username
