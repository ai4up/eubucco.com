from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _


class VersionEnum(models.IntegerChoices):
    V01 = 1, _("v0.1")
    VMSFT24 = 2, _("msft24")


def version_from_path(path):
    version_string = path.split("/")[-1].split("-")[0]
    if version_string == "v0_1":
        return VersionEnum.V01
    elif version_string == "vmsft24":
        return VersionEnum.VMSFT24
    else:
        raise ValueError(f"Unknown version {version_string}")
