def es_admin(user):
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name='Administrador').exists())

def es_entrenador(user):
    return user.is_authenticated and (
        user.groups.filter(name='Entrenador').exists() or hasattr(user, 'entrenador')
    )

def es_atleta(user):
    return user.is_authenticated and hasattr(user, 'atleta')  # por la OneToOne
