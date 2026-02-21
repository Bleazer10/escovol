# atletas/utils/roles.py
from django.core.exceptions import ObjectDoesNotExist

def es_admin(user):
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name='Administrador').exists())

def es_entrenador(user):
    # Ahora que los modelos usuarios locales pueden ser solo UUIDs en los
    # modelos (no FK), confiamos en la pertenencia a grupos para determinar
    # roles del usuario autenticado.
    if not user.is_authenticated:
        return False
    try:
        return user.groups.filter(name='Entrenador').exists()
    except Exception:
        return False

def es_atleta(user):
    if not user.is_authenticated:
        return False
    try:
        return user.groups.filter(name='Atleta').exists()
    except Exception:
        return False