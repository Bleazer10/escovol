# atletas/signals.py

from django.db.models.signals import post_save, post_migrate
from django.dispatch import receiver
from datetime import date
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db.utils import ProgrammingError, OperationalError


@receiver(post_save, sender='atletas.Atleta')
def crear_mensualidades_para_nuevo_atleta(sender, instance, created, **kwargs):
    """Crea las 12 mensualidades del año al registrar un nuevo atleta."""
    if created:
        from .models import Mensualidad
        año_actual = date.today().year
        for mes in range(1, 13):
            Mensualidad.objects.get_or_create(
                atleta=instance,
                año=año_actual,
                mes=mes,
                defaults={"monto_pagado": 0.00, "exonerado": False}
            )


@receiver(post_migrate)
def crear_roles_y_permisos(sender, **kwargs):
    """
    Crea/actualiza los 3 grupos con sus permisos después de cada migrate.

    Grupos:
      Administrador → todos los permisos
      Entrenador    → view de todo + CRUD en Equipo, Campeonato, Partido, Estadistica
      Atleta        → view_atleta + view_estadistica
    """
    if sender.name != 'atletas':
        return

    try:
        # Importaciones diferidas para evitar problemas en migraciones tempranas
        from .models import Atleta, Mensualidad, Entrenador, Equipo, Campeonato, Partido, Estadistica

        # ── Grupos ──────────────────────────────────────────────────────────
        administrador, _ = Group.objects.get_or_create(name='Administrador')
        entrenador_grp,  _ = Group.objects.get_or_create(name='Entrenador')
        atleta_grp,      _ = Group.objects.get_or_create(name='Atleta')

        # ── Administrador: TODOS los permisos ────────────────────────────────
        administrador.permissions.set(Permission.objects.all())

        # ── Entrenador: view de todo + CRUD en modelos permitidos ────────────
        perms_view = list(Permission.objects.filter(codename__startswith='view_'))
        entrenador_grp.permissions.set(perms_view)

        modelos_crud_entrenador = [Equipo, Campeonato, Partido, Estadistica]
        for modelo in modelos_crud_entrenador:
            try:
                ct = ContentType.objects.get_for_model(modelo)
                nombre = modelo._meta.model_name
                perms_crud = Permission.objects.filter(
                    content_type=ct,
                    codename__in=[
                        f'add_{nombre}',
                        f'change_{nombre}',
                        f'delete_{nombre}',
                    ]
                )
                entrenador_grp.permissions.add(*list(perms_crud))
            except Exception:
                continue

        # ── Atleta: solo view_atleta y view_estadistica ──────────────────────
        try:
            ct_atleta      = ContentType.objects.get_for_model(Atleta)
            ct_estadistica = ContentType.objects.get_for_model(Estadistica)
            perms_atleta = Permission.objects.filter(
                codename__in=['view_atleta', 'view_estadistica'],
                content_type__in=[ct_atleta, ct_estadistica]
            )
            atleta_grp.permissions.set(list(perms_atleta))
        except Exception:
            pass

        print("✅ Roles y permisos actualizados correctamente")

    except (ProgrammingError, OperationalError):
        # Base de datos aún no lista (primer migrate inicial)
        pass
    except Exception as e:
        print(f"⚠️ Error en señal post_migrate: {e}")