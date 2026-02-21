# atletas/signals.py
from django.db.models.signals import post_save, post_migrate
from django.dispatch import receiver
from datetime import date
from .models import Atleta, Mensualidad, Entrenador, Equipo, Campeonato, Partido, Estadistica
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.apps import apps
from django.db.utils import ProgrammingError, OperationalError

@receiver(post_save, sender=Atleta)
def crear_mensualidades_para_nuevo_atleta(sender, instance, created, **kwargs):
    """Esta función está bien, no necesita cambios"""
    if created:
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
    Crea/actualiza 3 grupos:
      - Administrador: TODOS los permisos
      - Entrenador: puede ver todo, y CRUD en Campeonatos, Partidos, Equipos, Estadísticas
      - Atleta: solo view de Atleta y Estadística
    """
    # Solo ejecutar para la app 'atletas'
    if sender.name != 'atletas':
        return
    
    try:
        # ===== Grupos =====
        administrador, _ = Group.objects.get_or_create(name='Administrador')
        entrenador, _ = Group.objects.get_or_create(name='Entrenador')
        atleta_group, _ = Group.objects.get_or_create(name='Atleta')

        # ===== Administrador: TODOS los permisos =====
        administrador.permissions.set(Permission.objects.all())

        # ===== Entrenador =====
        # Puede ver todo (permisos view_)
        perms_view = Permission.objects.filter(codename__startswith='view_')
        entrenador.permissions.set(perms_view)

        # CRUD permitido (Equipos, Campeonatos, Partidos, Estadísticas)
        modelos_crud_entrenador = [Equipo, Campeonato, Partido, Estadistica]
        
        for modelo in modelos_crud_entrenador:
            try:
                ct = ContentType.objects.get_for_model(modelo)
                perms_crud = Permission.objects.filter(
                    content_type=ct,
                    codename__in=[f'add_{modelo._meta.model_name}', 
                                  f'change_{modelo._meta.model_name}',
                                  f'delete_{modelo._meta.model_name}']
                )
                entrenador.permissions.add(*list(perms_crud))
            except (ContentType.DoesNotExist, Permission.DoesNotExist):
                # Si algún permiso no existe aún, lo ignoramos
                continue

        # ===== Atleta =====
        try:
            ct_atleta = ContentType.objects.get_for_model(Atleta)
            ct_estadistica = ContentType.objects.get_for_model(Estadistica)
            
            p_view_atleta = Permission.objects.get(codename='view_atleta', content_type=ct_atleta)
            p_view_estadistica = Permission.objects.get(codename='view_estadistica', content_type=ct_estadistica)
            
            atleta_group.permissions.set([p_view_atleta, p_view_estadistica])
        except (ContentType.DoesNotExist, Permission.DoesNotExist):
            # Si no existen, los creamos la próxima vez
            pass

        print("✅ Roles y permisos actualizados correctamente")
        
    except (ProgrammingError, OperationalError):
        # La base de datos aún no está lista (primer migrate)
        # Ignoramos silenciosamente
        pass
    except Exception as e:
        # Cualquier otro error, lo imprimimos pero no detenemos la ejecución
        print(f"⚠️ Error en señal post_migrate: {e}")