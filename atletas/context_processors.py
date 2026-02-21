# atletas/context_processors.py
from django.core.exceptions import ObjectDoesNotExist
from .utils.roles import es_admin, es_entrenador

def role_flags(request):
    """Context processor con manejo de errores para la relación Atleta"""
    u = request.user
    
    # Valores por defecto
    flags = {
        'is_admin': u.is_authenticated and es_admin(u),
        'is_entrenador': u.is_authenticated and es_entrenador(u),
        'is_atleta': False,
    }
    
    # Intentar verificar si es atleta de manera segura
    if u.is_authenticated:
        try:
            # Verificar si existe el atributo atleta sin disparar consulta
            if hasattr(u, 'atleta'):
                # Intentar acceder para ver si realmente existe
                _ = u.atleta
                flags['is_atleta'] = True
        except ObjectDoesNotExist:
            # El atleta no existe, es False
            pass
        except Exception:j
            # Cualquier otro error (como el de tipos), asumimos False
            pass
    
    return flags