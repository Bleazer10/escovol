from django.contrib.auth.models import User, Group
from .models import Atleta, Entrenador, Administrador
from django.db import transaction

# ---- ATLETA ----
@transaction.atomic
def crear_usuario_para_atleta(
    atleta: Atleta,
    username: str,
    password: str,
    email: str = ''
):
    user = User.objects.create_user(
        username=username.strip(),
        email=email,
        password=password
    )

    atleta.user = user
    atleta.save()

    grupo = Group.objects.get(name='Atleta')
    user.groups.add(grupo)

    return user


# ---- ENTRENADOR ----
@transaction.atomic
def crear_usuario_para_entrenador(
    entrenador: Entrenador,
    username: str,
    password: str,
    email: str = ''
):
    user = User.objects.create_user(
        username=username.strip(),
        email=email,
        password=password
    )

    entrenador.user = user
    entrenador.save()

    grupo = Group.objects.get(name='Entrenador')
    user.groups.add(grupo)

    return user


# ---- ADMINISTRADOR ----
@transaction.atomic
def crear_usuario_para_administrador(
    admin: Administrador,
    username: str,
    password: str,
    email: str = ''
):
    user = User.objects.create_user(
        username=username.strip(),
        email=email,
        password=password
    )

    admin.usuario = user
    admin.save()

    grupo = Group.objects.get(name='Administrador')
    user.groups.add(grupo)

    return user

# ---- ELIMINACIÓN SEGURA DE USUARIOS ----
def eliminar_usuario_sin_perfil(user):
    """
    Elimina la cuenta de Django únicamente si ya no está asociada
    a ningún perfil del sistema.
    """
    if not user:
        return

    tiene_otro_perfil = (
        Atleta.objects.filter(user=user).exists()
        or Entrenador.objects.filter(user=user).exists()
        or Administrador.objects.filter(usuario=user).exists()
    )

    if not tiene_otro_perfil:
        user.delete()

