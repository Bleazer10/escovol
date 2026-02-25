from django.urls import path
from . import views

urlpatterns = [
    # =========================
    # ATLETAS
    # =========================
    path('lista/', views.lista_atletas, name='lista_atletas'),
    path('agregar/', views.agregar_atleta, name='agregar_atleta'),
    path('detalle/<int:atleta_id>/', views.detalle_atleta, name='detalle_atleta'),
    path('<int:atleta_id>/editar/', views.editar_atleta, name='editar_atleta'),
    path('<int:atleta_id>/eliminar/', views.eliminar_atleta, name='eliminar_atleta'),

    # =========================
    # MENSUALIDAD / ADMINISTRACIÓN
    # =========================
    path('administracion/', views.administracion, name='administracion'),
    path('mensualidad/<int:mensualidad_id>/actualizar/', views.actualizar_mensualidad, name='actualizar_mensualidad'),

    # =========================
    # EQUIPOS
    # =========================
    path('equipos/', views.listar_equipos, name='listar_equipos'),
    path('equipos/registrar/', views.registrar_equipo, name='registrar_equipo'),
    path('equipos/<int:equipo_id>/', views.detalle_equipo, name='detalle_equipo'),
    path('equipos/<int:equipo_id>/editar/', views.editar_equipo, name='editar_equipo'),
    path('equipos/<int:equipo_id>/eliminar/', views.eliminar_equipo, name='eliminar_equipo'),

    # =========================
    # REPORTES (solo los necesarios)
    # =========================
    path('reportes/pagos/', views.reporte_pagos_view, name='reporte_pagos_view'),
    path('reportes/exportar_pagos_excel/', views.exportar_pagos_excel, name='exportar_pagos_excel'),
    path('reportes/exportar_pagos_pdf/', views.exportar_pagos_pdf, name='exportar_pagos_pdf'),

    path('reportes/atletas/', views.reporte_atletas_view, name='reporte_atletas'),
    path('reporte-atletas/pdf/', views.reporte_atletas_pdf, name='reporte_atletas_pdf'),
    path('reporte-atletas/excel/', views.reporte_atletas_excel, name='reporte_atletas_excel'),

    path("reportes/equipos/", views.reporte_equipos, name="reporte_equipos"),
    path("reportes/equipos/<int:equipo_id>/pdf/", views.exportar_equipo_pdf, name="exportar_equipo_pdf"),

    # =========================
    # USUARIOS (reutiliza módulo de administradores)
    # =========================
    path("administradores/", views.lista_administradores, name="lista_administradores"),
    path("administradores/agregar/", views.agregar_administrador, name="agregar_administrador"),
    path("administradores/editar/<int:administrador_id>/", views.editar_administrador, name="editar_administrador"),
    path("administradores/eliminar/<int:administrador_id>/", views.eliminar_administrador, name="eliminar_administrador"),
    path("administradores/<int:pk>/", views.detalle_administrador, name="detalle_administrador"),
]
