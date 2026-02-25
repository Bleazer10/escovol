from .settings import *
from pathlib import Path

DESKTOP_MODE = True

# Carpeta de datos del cliente (persistente)
DATA_DIR = Path.home() / "Documents" / "SistemaVoleibol_LEO" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
    }
}

# Recomendado en local desktop
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
