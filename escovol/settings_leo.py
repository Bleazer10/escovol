from .settings import *
from pathlib import Path
import os

DESKTOP_MODE = True

# =========================
# Base de datos del cliente (persistente)
# =========================
DATA_DIR = Path.home() / "Documents" / "SistemaVoleibol_LEO" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(DATA_DIR / "db.sqlite3"),
    }
}

DEBUG = True

# =========================
# Hosts (desktop local)
# =========================
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

# =========================
# Static (desktop)
# =========================
# ✅ Corrige el STATIC_URL para que sea absoluto
STATIC_URL = "/static/"

# Mantén tus fuentes estáticas
STATICFILES_DIRS = [BASE_DIR / "static"]

# Donde collectstatic deja todo listo para servir
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")

# WhiteNoise storage (requiere collectstatic)
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
# Si quieres algo más simple mientras pruebas, usa este en vez del de arriba:
# STATICFILES_STORAGE = "whitenoise.storage.StaticFilesStorage"

# =========================
# Middleware (NO sobrescribir, solo insertar WhiteNoise)
# =========================
if "whitenoise.middleware.WhiteNoiseMiddleware" not in MIDDLEWARE:
    # Insertar justo después de SecurityMiddleware
    idx = 0
    for i, mw in enumerate(MIDDLEWARE):
        if mw == "django.middleware.security.SecurityMiddleware":
            idx = i + 1
            break
    MIDDLEWARE.insert(idx, "whitenoise.middleware.WhiteNoiseMiddleware")

# =========================
# Opcional: para desktop puedes cambiar redirect si quieres
# =========================
# LOGIN_REDIRECT_URL = "/atletas/menu/"
# LOGOUT_REDIRECT_URL = "bienvenida"
