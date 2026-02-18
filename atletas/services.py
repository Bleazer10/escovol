# atletas/services.py
"""
Punto de entrada para crear usuarios.
Delega a supabase_service.py en lugar de usar django.contrib.auth directamente.
"""

from .supabase_service import (
    crear_usuario_para_atleta,
    crear_usuario_para_entrenador,
    crear_usuario_para_administrador,
    actualizar_password_en_supabase,
    actualizar_email_en_supabase,
    eliminar_usuario_en_supabase,
)

__all__ = [
    'crear_usuario_para_atleta',
    'crear_usuario_para_entrenador',
    'crear_usuario_para_administrador',
    'actualizar_password_en_supabase',
    'actualizar_email_en_supabase',
    'eliminar_usuario_en_supabase',
]
