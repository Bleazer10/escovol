# atletas/utils/roles.py


def es_admin(user) -> bool:
    """
    Es administrador si:
      - is_superuser, O
      - pertenece al grupo 'Administrador'
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    try:
        return user.groups.filter(name='Administrador').exists()
    except Exception:
        return False


def es_entrenador(user) -> bool:
    """
    Es entrenador si pertenece al grupo 'Entrenador'.
    """
    if not user or not user.is_authenticated:
        return False
    try:
        return user.groups.filter(name='Entrenador').exists()
    except Exception:
        return False


def es_atleta(user) -> bool:
    """
    Es atleta si pertenece al grupo 'Atleta'.
    """
    if not user or not user.is_authenticated:
        return False
    try:
        return user.groups.filter(name='Atleta').exists()
    except Exception:
        return False