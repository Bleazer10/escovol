# atletas/context_processors.py

from .utils.roles import es_admin, es_entrenador, es_atleta
from .models import Atleta


def role_flags(request):
    """
    Context processor que inyecta en TODOS los templates las banderas de rol.

    Variables disponibles en templates:
      is_admin      → True si es Administrador o superuser
      is_entrenador → True si es Entrenador   (alias: is_trainer)
      is_trainer    → alias de is_entrenador   (compatibilidad con base.html)
      is_athlete    → True si es Atleta        (alias: is_atleta)
      is_atleta     → alias de is_athlete
      atleta_id     → ID del Atleta vinculado al usuario (solo para atletas)
      show_modules  → True si es admin o entrenador (ve el menú completo)
    """
    u = request.user

    if not u.is_authenticated:
        return {
            'is_admin':      False,
            'is_entrenador': False,
            'is_trainer':    False,
            'is_athlete':    False,
            'is_atleta':     False,
            'atleta_id':     None,
            'show_modules':  False,
        }

    admin     = es_admin(u)
    entrenador = es_entrenador(u)
    atleta_flag = es_atleta(u)

    # Buscar el objeto Atleta vinculado al usuario logueado.
    # Atleta.user almacena el UUID de Supabase = User.username en Django.
    atleta_id = None
    if atleta_flag:
        atleta_obj = Atleta.objects.filter(user=u.username).first()
        if atleta_obj:
            atleta_id = atleta_obj.id

    return {
        'is_admin':      admin,
        'is_entrenador': entrenador,
        'is_trainer':    entrenador,       # alias usado en base.html anterior
        'is_athlete':    atleta_flag,
        'is_atleta':     atleta_flag,      # alias
        'atleta_id':     atleta_id,
        'show_modules':  admin or entrenador,
    }