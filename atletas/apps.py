# atletas/apps.py
from django.apps import AppConfig

class AtletasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'atletas'

    def ready(self):
        import atletas.signals
