from django.contrib.auth.models import User, Group
from .models import Atleta, Entrenador, Administrador

# ---- ATLETA ----
def crear_usuario_para_atleta(atleta: Atleta, username: str, password: str, email: str = ''):
    user, created = User.objects.get_or_create(username=username, defaults={'email': email})
    if created:
        user.set_password(password)
        user.save()
    atleta.user = user
    atleta.save()
    # Añadir al grupo Atleta
    g = Group.objects.get(name='Atleta')
    user.groups.add(g)
    return user

# ---- ENTRENADOR ----
def crear_usuario_para_entrenador(entrenador: Entrenador, username: str, password: str, email: str = ''):
    user, created = User.objects.get_or_create(username=username, defaults={'email': email})
    if created:
        user.set_password(password)
        user.save()
    entrenador.user = user
    entrenador.save()
    # Añadir al grupo Entrenador
    g = Group.objects.get(name='Entrenador')
    user.groups.add(g)
    return user

# ---- ADMINISTRADOR ----
def crear_usuario_para_administrador(admin: Administrador, username: str, password: str, email: str = ''):
    user, created = User.objects.get_or_create(username=username, defaults={'email': email})
    if created:
        user.set_password(password)
        user.save()
    admin.usuario = user
    admin.save()
    # Añadir al grupo Administrador
    g = Group.objects.get(name='Administrador')
    user.groups.add(g)
    return user
