import os
import sys
from pathlib import Path

import django
from django.core.asgi import get_asgi_application

# This allows easy placement of apps within the interior
# eubucco directory.
ROOT_DIR = Path(__file__).resolve(strict=True).parent.parent
sys.path.append(str(ROOT_DIR / "eubucco"))

# If DJANGO_SETTINGS_MODULE is unset, default to the local settings
if "DEVELOPMENT" in os.environ:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
else:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

# This application object is used by any ASGI server configured to use this file.
django_application = get_asgi_application()
django.setup()

from .v0_1.api import api  # noqa: F401 E402
