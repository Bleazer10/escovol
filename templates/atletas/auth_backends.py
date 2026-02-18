# atletas/auth_backends.py
"""
Backend de autenticación que valida credenciales contra Supabase Auth
y sincroniza el User de Django correspondiente.

Flujo:
  1. El usuario envía username/email + password en el formulario de login.
  2. Si recibió un username (sin @), resuelve el email buscando el User local.
  3. Llama a Supabase Auth (signInWithPassword).
  4. Si Supabase confirma, busca o crea el User de Django usando el UUID
     de Supabase como username (garantiza unicidad global).
  5. Django mantiene la sesión normalmente.

IMPORTANTE: El panel /admin/ sigue funcionando con ModelBackend como fallback.
"""

import logging
from django.contrib.auth.models import User
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_supabase_client():
    """Devuelve un cliente Supabase con la clave anónima (para login)."""
    try:
        from supabase import create_client
        return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    except ImportError:
        logger.error("Paquete 'supabase' no instalado. Ejecuta: pip install supabase")
        return None


class SupabaseAuthBackend:

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        # Si Supabase no está configurado, pasar al siguiente backend
        if not getattr(settings, 'SUPABASE_URL', ''):
            return None

        supabase = _get_supabase_client()
        if supabase is None:
            return None

        email = _resolver_email(username)
        if not email:
            return None

        try:
            response = supabase.auth.sign_in_with_password({
                "email": email,
                "password": password,
            })
        except Exception as exc:
            logger.warning("Supabase auth error para '%s': %s", email, exc)
            return None

        if not response or not response.user:
            return None

        return _sync_django_user(str(response.user.id), response.user)

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _resolver_email(valor: str) -> str | None:
    """
    Si contiene '@' lo devuelve tal cual.
    Si no, busca el User de Django con ese username y retorna su email.
    """
    if '@' in valor:
        return valor
    try:
        user = User.objects.get(username=valor)
        return user.email or None
    except User.DoesNotExist:
        return None


def _sync_django_user(supabase_uuid: str, supa_user) -> User:
    """
    Obtiene o crea el User de Django vinculado al UUID de Supabase.
    El username del User local ES el UUID de Supabase.
    """
    meta = supa_user.user_metadata or {}
    email = supa_user.email or ''

    # Buscar por UUID primero, luego por email como fallback de migración
    user = (
        User.objects.filter(username=supabase_uuid).first()
        or User.objects.filter(email=email).first()
    )

    if user is None:
        user = User(
            username=supabase_uuid,
            email=email,
            first_name=meta.get('first_name', ''),
            last_name=meta.get('last_name', ''),
            is_superuser=bool(meta.get('is_superuser', False)),
            is_staff=bool(meta.get('is_superuser', False)),
            is_active=True,
        )
        user.set_unusable_password()
        user.save()
        logger.info("Nuevo User Django creado para UUID Supabase: %s", supabase_uuid)
    else:
        # Sincronizar UUID como username si aún no lo era
        changed = False
        if user.username != supabase_uuid:
            user.username = supabase_uuid
            changed = True
        if email and user.email != email:
            user.email = email
            changed = True
        if changed:
            user.save()

    return user
