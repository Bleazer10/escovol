# atletas/context_processors.py
from django.core.exceptions import ObjectDoesNotExist
from .utils.roles import es_admin, es_entrenador, es_atleta
from .models import Atleta


def role_flags(request):
    """Context processor que expone banderas de rol y atleta_id cuando corresponda.

    Devuelve claves compatibles con las plantillas: `is_admin`, `is_trainer`,
    `is_entrenador`, `is_athlete`, `is_atleta`, y `atleta_id`.
    """
    u = request.user

    flags = {
        'is_admin': u.is_authenticated and es_admin(u),
        'is_trainer': u.is_authenticated and es_entrenador(u),
        'is_entrenador': u.is_authenticated and es_entrenador(u),
        'is_athlete': False,
        'is_atleta': False,
        'atleta_id': None,
    }

    if u.is_authenticated:
        try:
            # Determinar si el usuario tiene un atleta asociado buscando por username (UUID)
            supa_uuid = getattr(u, 'username', None)
            if supa_uuid:
                atleta = Atleta.objects.filter(user=supa_uuid).first()
                if atleta:
                    flags['is_atleta'] = True
                    flags['is_athlete'] = True
                    flags['atleta_id'] = atleta.id
            # Mostrar módulos si tiene algún rol, es staff o superuser
            flags['show_modules'] = bool(
                flags['is_admin'] or flags['is_trainer'] or flags['is_atleta'] or getattr(u, 'is_staff', False) or getattr(u, 'is_superuser', False)
            )
        except Exception:
            # Si algo falla, dejamos los flags por defecto
            pass

    return flags