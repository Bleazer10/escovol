# atletas/supabase_service.py
"""
Funciones para gestionar usuarios en Supabase Auth desde Django.
Requiere SUPABASE_SERVICE_ROLE_KEY para operaciones administrativas.

Úsalo desde services.py en lugar de User.objects.create_user().
"""

import logging
from django.conf import settings
from django.contrib.auth.models import User, Group

logger = logging.getLogger(__name__)


def _admin_client():
    """Cliente Supabase con privilegios de administrador (service_role)."""
    try:
        from supabase import create_client
        return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    except ImportError:
        logger.error("Paquete 'supabase' no instalado. Ejecuta: pip install supabase")
        return None


# ─── Operaciones sobre Supabase Auth ────────────────────────────────────────

def crear_usuario_en_supabase(email: str, password: str, metadata: dict = None) -> dict | None:
    """
    Crea un usuario en Supabase Auth.
    Devuelve {'uuid': ..., 'email': ...} o None si falla.
    """
    client = _admin_client()
    if not client:
        return None

    try:
        response = client.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,      # confirma automáticamente
            "user_metadata": metadata or {},
        })
        if response and response.user:
            logger.info("Usuario creado en Supabase: %s (%s)", email, response.user.id)
            return {"uuid": str(response.user.id), "email": email}
    except Exception as exc:
        logger.error("Error creando usuario en Supabase (%s): %s", email, exc)

    return None


def eliminar_usuario_en_supabase(supabase_uuid: str) -> bool:
    """Elimina un usuario de Supabase Auth por su UUID."""
    client = _admin_client()
    if not client:
        return False
    try:
        client.auth.admin.delete_user(supabase_uuid)
        logger.info("Usuario Supabase eliminado: %s", supabase_uuid)
        return True
    except Exception as exc:
        logger.error("Error eliminando usuario Supabase (%s): %s", supabase_uuid, exc)
        return False


def actualizar_password_en_supabase(supabase_uuid: str, nueva_password: str) -> bool:
    """Cambia la contraseña de un usuario en Supabase Auth."""
    client = _admin_client()
    if not client:
        return False
    try:
        client.auth.admin.update_user_by_id(
            supabase_uuid,
            {"password": nueva_password}
        )
        logger.info("Password actualizada en Supabase para: %s", supabase_uuid)
        return True
    except Exception as exc:
        logger.error("Error actualizando password Supabase (%s): %s", supabase_uuid, exc)
        return False


def actualizar_email_en_supabase(supabase_uuid: str, nuevo_email: str) -> bool:
    """Cambia el email de un usuario en Supabase Auth."""
    client = _admin_client()
    if not client:
        return False
    try:
        client.auth.admin.update_user_by_id(
            supabase_uuid,
            {"email": nuevo_email, "email_confirm": True}
        )
        return True
    except Exception as exc:
        logger.error("Error actualizando email Supabase (%s): %s", supabase_uuid, exc)
        return False


# ─── Helper local ────────────────────────────────────────────────────────────

def _crear_user_django(uuid: str, email: str, metadata: dict) -> User:
    """Crea (o actualiza) el User de Django vinculado al UUID de Supabase."""
    user, created = User.objects.get_or_create(
        username=uuid,
        defaults={
            "email": email,
            "first_name": metadata.get("first_name", ""),
            "last_name": metadata.get("last_name", ""),
            "is_active": True,
        }
    )
    if created:
        user.set_unusable_password()
        user.save()
    return user


# ─── Funciones de alto nivel (usadas por services.py) ───────────────────────

def crear_usuario_para_atleta(atleta, username: str, password: str, email: str = '') -> User:
    email = email or f"{username}@escovol.local"
    metadata = {"username": username, "rol": "atleta"}

    resultado = crear_usuario_en_supabase(email, password, metadata)
    if not resultado:
        raise RuntimeError(f"No se pudo crear usuario en Supabase para '{username}'")

    user = _crear_user_django(resultado["uuid"], email, metadata)
    group, _ = Group.objects.get_or_create(name='Atleta')
    user.groups.add(group)

    atleta.user = user
    atleta.save()
    return user


def crear_usuario_para_entrenador(entrenador, username: str, password: str, email: str = '') -> User:
    email = email or f"{username}@escovol.local"
    metadata = {"username": username, "rol": "entrenador"}

    resultado = crear_usuario_en_supabase(email, password, metadata)
    if not resultado:
        raise RuntimeError(f"No se pudo crear usuario en Supabase para '{username}'")

    user = _crear_user_django(resultado["uuid"], email, metadata)
    group, _ = Group.objects.get_or_create(name='Entrenador')
    user.groups.add(group)

    entrenador.user = user
    entrenador.save()
    return user


def crear_usuario_para_administrador(admin_obj, username: str, password: str, email: str = '') -> User:
    email = email or f"{username}@escovol.local"
    metadata = {"username": username, "rol": "administrador"}

    resultado = crear_usuario_en_supabase(email, password, metadata)
    if not resultado:
        raise RuntimeError(f"No se pudo crear usuario en Supabase para '{username}'")

    user = _crear_user_django(resultado["uuid"], email, metadata)
    group, _ = Group.objects.get_or_create(name='Administrador')
    user.groups.add(group)

    admin_obj.usuario = user
    admin_obj.save()
    return user
