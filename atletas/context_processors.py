from .utils.roles import es_admin, es_entrenador, es_atleta

def role_flags(request):
    u = request.user
    atleta_id = None
    if u.is_authenticated and es_atleta(u):  # ✅ propiedad
        if hasattr(u, "atleta"):
            atleta_id = u.atleta.id

    return {
        "is_admin": es_admin(u),
        "is_trainer": es_entrenador(u),
        "is_athlete": es_atleta(u),
        "atleta_id": atleta_id,
    }
