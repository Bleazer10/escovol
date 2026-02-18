# # atletas/signals.py

# from django.db.models.signals import post_save, post_migrate
# from django.dispatch import receiver
# from datetime import date
# from .models import Atleta, Mensualidad, Entrenador, Equipo, Campeonato, Partido, Estadistica
# from django.contrib.auth.models import Group, Permission
# from django.contrib.contenttypes.models import ContentType

# @receiver(post_save, sender=Atleta)
# def crear_mensualidades_para_nuevo_atleta(sender, instance, created, **kwargs):
#     if created:
#         año_actual = date.today().year
#         for mes in range(1, 13):
#             Mensualidad.objects.get_or_create(
#                 atleta=instance,
#                 año=año_actual,
#                 mes=mes,
#                 defaults={"monto_pagado": 0.00, "exonerado": False}
#             )

# @receiver(post_migrate)
# def crear_roles_y_permisos(sender, **kwargs):
#     """
#     Crea/actualiza 3 grupos:
#       - Administrador: TODOS los permisos
#       - Entrenador: puede ver todo, y CRUD en Campeonatos, Partidos, Equipos, Estadísticas
#       - Atleta: solo view de Atleta y Estadística
#     """
#     # ===== Grupos =====
#     administrador, _ = Group.objects.get_or_create(name='Administrador')
#     entrenador, _ = Group.objects.get_or_create(name='Entrenador')
#     atleta_group, _ = Group.objects.get_or_create(name='Atleta')

#     # ===== Administrador: TODOS los permisos =====
#     administrador.permissions.set(Permission.objects.all())

#     # ===== Entrenador =====
#     # Puede ver todo
#     perms_view = Permission.objects.filter(codename__startswith='view_')
#     entrenador.permissions.set(perms_view)

#     # CRUD permitido (Equipos, Campeonatos, Partidos, Estadísticas)
#     modelos_crud_entrenador = [Equipo, Campeonato, Partido, Estadistica]
#     cts = [ContentType.objects.get_for_model(m) for m in modelos_crud_entrenador]
#     perms_crud = Permission.objects.filter(
#         content_type__in=cts,
#         codename__regex=r'^(add|change|delete|view)_'
#     )
#     entrenador.permissions.add(*list(perms_crud))

#     # Nota: NO agregamos permisos de Atleta, Entrenador ni Usuarios → solo admin los tendrá.

#     # ===== Atleta =====
#     ct_atleta = ContentType.objects.get_for_model(Atleta)
#     ct_estadistica = ContentType.objects.get_for_model(Estadistica)
#     p_view_atleta = Permission.objects.get(codename='view_atleta', content_type=ct_atleta)
#     p_view_estadistica = Permission.objects.get(codename='view_estadistica', content_type=ct_estadistica)
#     atleta_group.permissions.set([p_view_atleta, p_view_estadistica])

#     # Listo. Grupos/permisos actualizados.
