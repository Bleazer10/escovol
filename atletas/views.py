# atletas/views.py
# ─── CAMBIOS RESPECTO A LA VERSIÓN ANTERIOR ──────────────────────────────────
# 1. editar_atleta:       usa form.apply_to_user() + actualizar_password_en_supabase()
# 2. editar_entrenador:   ídem
# 3. editar_administrador: ídem
# 4. Import: se agrega actualizar_password_en_supabase, actualizar_email_en_supabase
# TODO: El resto del archivo es idéntico al original. Solo se muestran las
#       funciones modificadas para facilitar la revisión del diff.
# ─────────────────────────────────────────────────────────────────────────────

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Atleta, Mensualidad, Estadistica, Entrenador, Campeonato, Partido, Equipo, Administrador
from .forms import AtletaForm, EstadisticaForm, EntrenadorForm, CampeonatoForm, PartidoForm, EquipoForm, UsuarioForm, AdministradorForm
from django.core.paginator import Paginator
from datetime import date
from django.views.decorators.http import require_POST, require_http_methods
from django.db.models import Sum, Count, Q
from calendar import month_name
from django.db.models.functions import ExtractYear
from django.contrib import messages
from django.contrib.auth.models import User
from django.db import models
from django.db import IntegrityError
from django.utils import timezone
from datetime import timedelta, datetime
from django.contrib.auth import authenticate, login
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from django.http import FileResponse, HttpResponse
import io
import pandas as pd
import calendar
import os
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.utils import ImageReader
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
import openpyxl
from django.conf import settings
from io import BytesIO
from django.utils.timezone import localtime
from django.template.loader import get_template
import base64
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib.units import inch
from collections import defaultdict
import numpy as np
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from django.db.models import Prefetch
from django.utils.dateparse import parse_date
from django.utils.encoding import escape_uri_path
from .utils.roles import es_admin, es_entrenador, es_atleta
from django.contrib import admin
from django.contrib.auth.hashers import make_password
from .services import (
    crear_usuario_para_atleta,
    crear_usuario_para_administrador,
    crear_usuario_para_entrenador,
    actualizar_password_en_supabase,
    actualizar_email_en_supabase,
)


# ─── Helpers internos ────────────────────────────────────────────────────────

def _get_supabase_uuid(user: User) -> str | None:
    """
    Devuelve el UUID de Supabase almacenado como username del User de Django.
    Si el username no tiene formato UUID (36 chars con guiones), devuelve None.
    """
    if user and len(user.username) == 36 and user.username.count('-') == 4:
        return user.username
    return None


# ─── Vistas de Atletas ───────────────────────────────────────────────────────

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def lista_atletas(request):
    atletas = Atleta.objects.all()

    categoria = request.GET.get('categoria')
    sexo = request.GET.get('sexo')
    posicion = request.GET.get('posicion')
    turno = request.GET.get('turno')
    numero = request.GET.get('numero')
    cedula = request.GET.get('cedula')

    if categoria:
        atletas = atletas.filter(categoria=categoria)
    if sexo:
        atletas = atletas.filter(sexo=sexo)
    if posicion:
        atletas = atletas.filter(posicion=posicion)
    if turno:
        atletas = atletas.filter(turno=turno)
    if numero:
        atletas = atletas.filter(numero_camisa=numero)
    if cedula:
        atletas = atletas.filter(cedula__icontains=cedula)

    atletas = atletas.order_by("apellido", "nombre", "id")

    paginator = Paginator(atletas, 8)
    page_number = request.GET.get('page')
    atletas = paginator.get_page(page_number)

    categorias = Atleta.objects.values_list('categoria', flat=True).distinct()
    posiciones = Atleta.POSICIONES
    turnos = Atleta.TURNOS
    sexos = Atleta.SEXO

    return render(request, 'atletas/lista_atletas.html', {
        'atletas': atletas,
        'categorias': categorias,
        'posiciones': posiciones,
        'turnos': turnos,
        'sexos': sexos,
        'valores': request.GET,
        'is_admin': es_admin(request.user),
        'is_entrenador': es_entrenador(request.user),
    })


@user_passes_test(es_admin)
def agregar_atleta(request):
    if request.method == 'POST':
        atleta_form = AtletaForm(request.POST)
        usuario_form = UsuarioForm(request.POST)

        if atleta_form.is_valid() and usuario_form.is_valid():
            atleta = atleta_form.save(commit=False)
            username = usuario_form.cleaned_data['username']
            password = usuario_form.cleaned_data['password']
            email = usuario_form.cleaned_data.get('email', '')

            try:
                crear_usuario_para_atleta(atleta, username, password, email)
                messages.success(request, 'Atleta creado correctamente.')
                return redirect('lista_atletas')
            except RuntimeError as e:
                messages.error(request, str(e))
    else:
        atleta_form = AtletaForm()
        usuario_form = UsuarioForm()

    return render(request, 'atletas/agregar_atleta.html', {
        'form': atleta_form,
        'usuario_form': usuario_form
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u) or es_atleta(u))
def detalle_atleta(request, atleta_id):
    atleta = get_object_or_404(Atleta, id=atleta_id)

    if es_atleta(request.user) and atleta.user != request.user:
        return redirect('bienvenida')

    despegue = None
    if atleta.salto is not None and atleta.alcance is not None:
        despegue = round((atleta.salto - atleta.alcance) * 100, 2)

    return render(request, 'atletas/detalle_atleta.html', {
        'atleta': atleta,
        'despegue': despegue,
    })


@user_passes_test(es_admin)
def editar_atleta(request, atleta_id):
    atleta = get_object_or_404(Atleta, id=atleta_id)
    usuario = getattr(atleta, "user", None)

    if request.method == 'POST':
        form = AtletaForm(request.POST, instance=atleta)
        usuario_form = UsuarioForm(request.POST, instance=usuario)

        if form.is_valid() and usuario_form.is_valid():
            form.save()

            if usuario:
                # Aplicar cambios de email/estado al User de Django
                usuario_form.apply_to_user(usuario)

                # Si escribió nueva contraseña, actualizarla en Supabase
                nueva_password = usuario_form.get_password()
                if nueva_password:
                    supabase_uuid = _get_supabase_uuid(usuario)
                    if supabase_uuid:
                        ok = actualizar_password_en_supabase(supabase_uuid, nueva_password)
                        if not ok:
                            messages.warning(request, 'Datos guardados pero no se pudo actualizar la contraseña en Supabase.')
                    else:
                        messages.warning(request, 'No se encontró el UUID de Supabase para este usuario.')

            return redirect('detalle_atleta', atleta_id=atleta.id)
    else:
        form = AtletaForm(instance=atleta)
        usuario_form = UsuarioForm(instance=usuario)

    return render(request, 'atletas/editar_atleta.html', {
        'form': form,
        'atleta': atleta,
        'usuario_form': usuario_form,
        'is_admin': es_admin(request.user),
    })


@user_passes_test(es_admin)
def eliminar_atleta(request, atleta_id):
    atleta = get_object_or_404(Atleta, id=atleta_id)
    if request.method == 'POST':
        atleta.delete()
        return redirect('lista_atletas')
    return render(request, 'atletas/eliminar_atleta.html', {'atleta': atleta})


@require_POST
def actualizar_mensualidad(request, mensualidad_id):
    mensualidad = get_object_or_404(Mensualidad, id=mensualidad_id)
    monto = request.POST.get("monto", 0)
    exonerado = 'exonerado' in request.POST

    try:
        mensualidad.monto_pagado = float(monto)
    except ValueError:
        mensualidad.monto_pagado = 0

    mensualidad.exonerado = exonerado
    mensualidad.save()
    return redirect('administracion')


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def administracion(request):
    mes_actual = date.today().month
    año_actual = int(request.GET.get("año", date.today().year))
    mes_filtro = int(request.GET.get("mes", mes_actual))
    categoria_filtro = request.GET.get("categoria", "")

    atletas = Atleta.objects.all()
    if categoria_filtro:
        atletas = atletas.filter(categoria=categoria_filtro)

    for atleta in atletas:
        for mes in range(1, 13):
            Mensualidad.objects.get_or_create(
                atleta=atleta, mes=mes, año=año_actual,
                defaults={"monto_pagado": 0.00, "exonerado": False}
            )
    siguiente_año = año_actual + 1
    for atleta in atletas:
        for mes in range(1, 13):
            Mensualidad.objects.get_or_create(
                atleta=atleta, mes=mes, año=siguiente_año,
                defaults={"monto_pagado": 0.00, "exonerado": False}
            )

    registros = []
    for atleta in atletas:
        mensualidad = Mensualidad.objects.filter(atleta=atleta, mes=mes_filtro, año=año_actual).first()
        registros.append({"atleta": atleta, "mensualidad": mensualidad})

    mensualidades_mes = Mensualidad.objects.filter(mes=mes_filtro, año=año_actual)
    if categoria_filtro:
        mensualidades_mes = mensualidades_mes.filter(atleta__categoria=categoria_filtro)

    total_recaudado = mensualidades_mes.aggregate(total=Sum("monto_pagado"))["total"] or 0
    total_atletas = mensualidades_mes.count()
    al_dia = exonerados = 0
    for m in mensualidades_mes:
        if m.estado() == "Al día":
            al_dia += 1
        elif m.estado() == "Exonerado":
            exonerados += 1
    deudores = total_atletas - al_dia - exonerados

    paginator = Paginator(registros, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    meses = [(i, date(1900, i, 1).strftime('%B')) for i in range(1, 13)]
    categorias = Atleta.objects.values_list("categoria", flat=True).distinct()

    return render(request, 'atletas/administracion.html', {
        "page_obj": page_obj,
        "mes_filtro": mes_filtro,
        "mes_actual": mes_actual,
        "año_actual": año_actual,
        "categorias": categorias,
        "categoria_filtro": categoria_filtro,
        "meses": meses,
        "total_recaudado": total_recaudado,
        "al_dia": al_dia,
        "exonerados": exonerados,
        "deudores": deudores,
        "total_atletas": total_atletas,
    })


# ─── Vistas de Entrenadores ──────────────────────────────────────────────────

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def lista_entrenadores(request):
    entrenadores = Entrenador.objects.all().order_by('nombre')
    paginator = Paginator(entrenadores, 10)
    page = request.GET.get('page')
    page_obj = paginator.get_page(page)
    return render(request, 'entrenadores/lista_entrenadores.html', {
        'entrenadores': page_obj,
        'page_obj': page_obj,
        'is_admin': es_admin(request.user),
        'is_entrenador': es_entrenador(request.user),
    })


@user_passes_test(es_admin)
def registrar_entrenador(request):
    if request.method == 'POST':
        usuario_form = UsuarioForm(request.POST)
        entrenador_form = EntrenadorForm(request.POST)

        if usuario_form.is_valid() and entrenador_form.is_valid():
            entrenador = entrenador_form.save(commit=False)
            username = usuario_form.cleaned_data['username']
            password = usuario_form.cleaned_data['password']
            email = usuario_form.cleaned_data.get('email', '')

            try:
                crear_usuario_para_entrenador(entrenador, username, password, email)
                messages.success(request, 'Entrenador registrado correctamente.')
                return redirect('lista_entrenadores')
            except RuntimeError as e:
                messages.error(request, str(e))
    else:
        usuario_form = UsuarioForm()
        entrenador_form = EntrenadorForm()

    return render(request, 'entrenadores/registrar_entrenador.html', {
        'usuario_form': usuario_form,
        'form': entrenador_form
    })


@user_passes_test(es_admin)
def detalle_entrenador(request, entrenador_id):
    entrenador = get_object_or_404(Entrenador, id=entrenador_id)
    usuario = getattr(entrenador, "user", None)
    return render(request, 'entrenadores/detalle_entrenador.html', {
        'entrenador': entrenador,
        'usuario': usuario,
    })


@user_passes_test(es_admin)
def editar_entrenador(request, entrenador_id):
    entrenador = get_object_or_404(Entrenador, id=entrenador_id)
    usuario = getattr(entrenador, "user", None)

    if request.method == 'POST':
        form = EntrenadorForm(request.POST, instance=entrenador)
        usuario_form = UsuarioForm(request.POST, instance=usuario)

        if form.is_valid() and usuario_form.is_valid():
            form.save()

            if usuario:
                usuario_form.apply_to_user(usuario)

                nueva_password = usuario_form.get_password()
                if nueva_password:
                    supabase_uuid = _get_supabase_uuid(usuario)
                    if supabase_uuid:
                        ok = actualizar_password_en_supabase(supabase_uuid, nueva_password)
                        if not ok:
                            messages.warning(request, 'Datos guardados pero no se pudo actualizar la contraseña en Supabase.')

            return redirect('detalle_entrenador', entrenador_id=entrenador.id)
    else:
        form = EntrenadorForm(instance=entrenador)
        usuario_form = UsuarioForm(instance=usuario)

    return render(request, 'entrenadores/editar_entrenador.html', {
        'form': form,
        'usuario_form': usuario_form,
        'entrenador': entrenador,
    })


@user_passes_test(es_admin)
def eliminar_entrenador(request, entrenador_id):
    entrenador = get_object_or_404(Entrenador, id=entrenador_id)
    if request.method == 'POST':
        entrenador.delete()
        messages.success(request, 'Entrenador eliminado con éxito.')
        return redirect('lista_entrenadores')
    return render(request, 'entrenadores/eliminar_entrenador.html', {'entrenador': entrenador})


# ─── Vistas de Administradores ───────────────────────────────────────────────

@user_passes_test(es_admin)
def lista_administradores(request):
    administradores = Administrador.objects.all().order_by("apellido")
    paginator = Paginator(administradores, 8)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    return render(request, "administradores/lista.html", {
        "page_obj": page_obj,
        "administradores": page_obj.object_list
    })


@user_passes_test(es_admin)
def agregar_administrador(request):
    if request.method == "POST":
        usuario_form = UsuarioForm(request.POST)
        administrador_form = AdministradorForm(request.POST)

        if usuario_form.is_valid() and administrador_form.is_valid():
            administrador = administrador_form.save(commit=False)
            username = usuario_form.cleaned_data['username']
            password = usuario_form.cleaned_data['password']
            email = usuario_form.cleaned_data.get('email', '')

            try:
                crear_usuario_para_administrador(administrador, username, password, email)
                messages.success(request, 'Administrador creado correctamente.')
                return redirect('lista_administradores')
            except RuntimeError as e:
                messages.error(request, str(e))
    else:
        usuario_form = UsuarioForm()
        administrador_form = AdministradorForm()

    return render(request, "administradores/agregar.html", {
        "usuario_form": usuario_form,
        "form": administrador_form
    })


@user_passes_test(es_admin)
def detalle_administrador(request, pk):
    administrador = get_object_or_404(Administrador, pk=pk)
    return render(request, 'administradores/detalle.html', {'administrador': administrador})


@user_passes_test(es_admin)
def editar_administrador(request, administrador_id):
    administrador = get_object_or_404(Administrador, id=administrador_id)
    usuario = administrador.usuario

    if request.method == "POST":
        form = AdministradorForm(request.POST, instance=administrador)
        usuario_form = UsuarioForm(request.POST, instance=usuario)

        if form.is_valid() and usuario_form.is_valid():
            form.save()
            usuario_form.apply_to_user(usuario)

            nueva_password = usuario_form.get_password()
            if nueva_password:
                supabase_uuid = _get_supabase_uuid(usuario)
                if supabase_uuid:
                    ok = actualizar_password_en_supabase(supabase_uuid, nueva_password)
                    if not ok:
                        messages.warning(request, 'Datos guardados pero no se pudo actualizar la contraseña en Supabase.')

            return redirect("detalle_administrador", administrador.id)
    else:
        form = AdministradorForm(instance=administrador)
        usuario_form = UsuarioForm(instance=usuario)

    return render(request, "administradores/editar.html", {
        "form": form,
        "usuario_form": usuario_form,
        "administrador": administrador,
    })


@user_passes_test(es_admin)
def eliminar_administrador(request, administrador_id):
    administrador = get_object_or_404(Administrador, id=administrador_id)
    if request.method == "POST":
        administrador.delete()
        return redirect("lista_administradores")
    return render(request, "administradores/eliminar.html", {"administrador": administrador})


# ─── Lista de usuarios ────────────────────────────────────────────────────────

@user_passes_test(es_admin)
def lista_usuarios(request):
    rol_filtro = request.GET.get('rol', '')
    estado_filtro = request.GET.get('estado', '')
    nombre_filtro = request.GET.get('nombre', '')

    usuarios = []

    for e in Entrenador.objects.select_related('user'):
        if not e.user:
            continue
        usuarios.append({
            'id': e.id, 'nombre': e.nombre, 'apellido': e.apellido,
            'usuario': e.user.email or e.user.username,
            'email': e.user.email, 'rol': 'Entrenador',
            'estado': 'Activo' if e.user.is_active else 'Inactivo',
        })

    for a in Atleta.objects.select_related('user'):
        if not a.user:
            continue
        usuarios.append({
            'id': a.id, 'nombre': a.nombre, 'apellido': a.apellido,
            'usuario': a.user.email or a.user.username,
            'email': a.user.email, 'rol': 'Atleta',
            'estado': 'Activo' if a.user.is_active else 'Inactivo',
        })

    for ad in Administrador.objects.select_related('usuario'):
        if not ad.usuario:
            continue
        usuarios.append({
            'id': ad.id, 'nombre': ad.nombre, 'apellido': ad.apellido,
            'usuario': ad.usuario.email or ad.usuario.username,
            'email': ad.usuario.email, 'rol': 'Administrador',
            'estado': 'Activo' if ad.usuario.is_active else 'Inactivo',
        })

    if rol_filtro:
        usuarios = [u for u in usuarios if u['rol'] == rol_filtro]
    if estado_filtro:
        usuarios = [u for u in usuarios if u['estado'] == estado_filtro]
    if nombre_filtro:
        usuarios = [u for u in usuarios if nombre_filtro.lower() in u['nombre'].lower()]

    paginator = Paginator(usuarios, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'usuarios/lista.html', {
        'page_obj': page_obj,
        'rol_filtro': rol_filtro,
        'estado_filtro': estado_filtro,
        'nombre_filtro': nombre_filtro,
    })


# ─── El resto de las vistas (Campeonatos, Equipos, Partidos, Estadísticas,
#     Reportes) NO cambian. Se copian sin modificación del archivo original.
# ─────────────────────────────────────────────────────────────────────────────

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def registrar_campeonato(request):
    if request.method == 'POST':
        form = CampeonatoForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('lista_campeonatos')
        else:
            messages.error(request, "Corrige los errores del formulario.")
    else:
        form = CampeonatoForm()
    return render(request, 'campeonatos/registrar_campeonato.html', {'form': form})


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def lista_campeonatos(request):
    campeonatos = Campeonato.objects.all().order_by('-anio')
    tipo = request.GET.get('tipo')
    anio = request.GET.get('anio')
    if tipo:
        campeonatos = campeonatos.filter(tipo=tipo)
    if anio:
        campeonatos = campeonatos.filter(anio=anio)
    paginator = Paginator(campeonatos, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'campeonatos/lista_campeonatos.html', {
        'campeonatos': page_obj,
        'page_obj': page_obj,
        'valores': {'tipo': tipo, 'anio': anio},
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def editar_campeonato(request, campeonato_id):
    campeonato = get_object_or_404(Campeonato, id=campeonato_id)
    if request.method == 'POST':
        form = CampeonatoForm(request.POST, instance=campeonato)
        if form.is_valid():
            form.save()
            return redirect('lista_campeonatos')
    else:
        form = CampeonatoForm(instance=campeonato)
    return render(request, 'campeonatos/editar_campeonato.html', {'form': form, 'campeonato': campeonato})


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def eliminar_campeonato(request, campeonato_id):
    campeonato = get_object_or_404(Campeonato, id=campeonato_id)
    if request.method == 'POST':
        campeonato.delete()
        return redirect('lista_campeonatos')
    return render(request, 'campeonatos/eliminar_campeonato.html', {'campeonato': campeonato})


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def detalle_campeonato(request, campeonato_id):
    campeonato = get_object_or_404(Campeonato, id=campeonato_id)
    return render(request, 'campeonatos/detalle_campeonato.html', {'campeonato': campeonato})


def calcular_edad(nacimiento):
    hoy = date.today()
    return hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def registrar_equipo(request):
    edad_tope = request.GET.get('edad_tope') or request.POST.get('edad_tope')
    sexo = request.GET.get('sexo') or request.POST.get('sexo')
    atletas_filtrados = []
    mostrar_formulario = False
    error_maximo = False

    if edad_tope and sexo:
        try:
            edad_tope = int(edad_tope)
            for atleta in Atleta.objects.all():
                edad = calcular_edad(atleta.fecha_nacimiento)
                if edad <= edad_tope and (sexo == 'mixto' or atleta.sexo == sexo):
                    atleta.edad = edad
                    atletas_filtrados.append(atleta)
            mostrar_formulario = True
        except ValueError:
            edad_tope = None

    if request.method == 'POST':
        form = EquipoForm(request.POST)
        atletas_ids = request.POST.getlist('atletas_seleccionados')
        if len(atletas_ids) > 14:
            error_maximo = True
            mostrar_formulario = True
        elif form.is_valid():
            equipo = form.save(commit=False)
            equipo.sexo_equipo = sexo
            equipo.edad_tope = edad_tope
            equipo.save()
            equipo.atletas.set(atletas_ids)
            return redirect('listar_equipos')
    else:
        form = EquipoForm()

    return render(request, 'equipos/registrar_equipo.html', {
        'form': form,
        'edad_tope': edad_tope,
        'sexo': sexo,
        'atletas_disponibles': atletas_filtrados,
        'atletas_seleccionados': request.POST.getlist('atletas_seleccionados') if request.method == 'POST' else [],
        'mostrar_formulario': mostrar_formulario,
        'error_maximo': error_maximo,
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def listar_equipos(request):
    equipos = Equipo.objects.select_related('entrenador').all().order_by('nombre')
    nombre = request.GET.get('nombre', '').strip()
    entrenador_id = request.GET.get('entrenador', '')
    if nombre:
        equipos = equipos.filter(nombre__icontains=nombre)
    if entrenador_id:
        equipos = equipos.filter(entrenador_id=entrenador_id)
    paginator = Paginator(equipos, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'equipos/listar_equipos.html', {
        'page_obj': page_obj,
        'entrenadores': Entrenador.objects.all(),
        'valores': {'nombre': nombre, 'entrenador': entrenador_id},
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def detalle_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, pk=equipo_id)
    atletas = equipo.atletas.all().order_by('nombre')
    for atleta in atletas:
        atleta.edad = calcular_edad(atleta.fecha_nacimiento)
    return render(request, 'equipos/detalle_equipo.html', {'equipo': equipo, 'atletas': atletas})


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def eliminar_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, pk=equipo_id)
    if request.method == 'POST':
        equipo.delete()
        return redirect('listar_equipos')
    return render(request, 'equipos/eliminar_equipo.html', {'equipo': equipo})


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def editar_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, pk=equipo_id)
    sexo = request.POST.get('sexo_equipo') or request.GET.get('sexo') or equipo.sexo_equipo
    edad_tope = request.GET.get('edad_tope') or request.POST.get('edad_tope')

    if not edad_tope:
        if equipo.edad_tope:
            edad_tope = equipo.edad_tope
        elif equipo.atletas.exists():
            edad_tope = max([calcular_edad(a.fecha_nacimiento) for a in equipo.atletas.all()])
        else:
            edad_tope = ''

    error_msg = None
    try:
        edad_tope_int = int(edad_tope)
        if edad_tope_int <= 0:
            raise ValueError
    except (ValueError, TypeError):
        edad_tope_int = None
        error_msg = "Edad tope inválida."

    atletas_filtrados = []
    if edad_tope_int:
        for atleta in Atleta.objects.all():
            edad = calcular_edad(atleta.fecha_nacimiento)
            if edad <= edad_tope_int and (sexo == 'mixto' or atleta.sexo == sexo):
                atleta.edad = edad
                atletas_filtrados.append(atleta)

    if request.method == 'POST':
        form = EquipoForm(request.POST, instance=equipo)
        atletas_ids = request.POST.getlist('atletas_seleccionados')
        if len(atletas_ids) > 14:
            error_msg = "Solo se pueden seleccionar hasta 14 atletas."
        elif form.is_valid():
            equipo = form.save(commit=False)
            equipo.sexo_equipo = sexo
            equipo.edad_tope = edad_tope_int
            equipo.save()
            equipo.atletas.set(atletas_ids)
            return redirect('detalle_equipo', equipo.id)
    else:
        form = EquipoForm(instance=equipo)
        atletas_ids = list(equipo.atletas.values_list('id', flat=True))

    return render(request, 'equipos/editar_equipo.html', {
        'form': form, 'equipo': equipo, 'sexo': sexo,
        'edad_tope': edad_tope, 'atletas_disponibles': atletas_filtrados,
        'atletas_seleccionados': atletas_ids, 'error_msg': error_msg,
        'mostrar_formulario': True,
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def registrar_partido(request):
    sets_con_datos = 1
    seis_meses_atras = timezone.now() - timedelta(days=180)
    campeonatos_recientes = Campeonato.objects.filter(fecha_inicio__gte=seis_meses_atras)

    if request.method == 'POST':
        form = PartidoForm(request.POST)
        form.fields['campeonato'].queryset = campeonatos_recientes
        for i in range(1, 6):
            if request.POST.get(f"set{i}_local") or request.POST.get(f"set{i}_externo"):
                sets_con_datos = i
        if form.is_valid():
            partido = form.save(commit=False)
            partido.ganador = form.cleaned_data.get("ganador")
            partido.save()
            return redirect('lista_partidos')
    else:
        form = PartidoForm()
        form.fields['campeonato'].queryset = campeonatos_recientes

    return render(request, 'partidos/registrar_partido.html', {'form': form, 'sets_con_datos': sets_con_datos})


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def lista_partidos(request):
    partidos = Partido.objects.order_by('-fecha', '-hora')
    equipo_id = request.GET.get('equipo', '').strip()
    campeonato_id = request.GET.get('campeonato', '').strip()
    estado = request.GET.get('estado', '').strip()
    if equipo_id:
        partidos = partidos.filter(equipo_local_id=equipo_id)
    if campeonato_id:
        partidos = partidos.filter(campeonato_id=campeonato_id)
    if estado:
        partidos = partidos.filter(estado=estado)
    paginator = Paginator(partidos, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'partidos/lista_partidos.html', {
        'page_obj': page_obj,
        'equipos': Equipo.objects.order_by('nombre'),
        'campeonatos': Campeonato.objects.order_by('-fecha_inicio'),
        'estados': [("programado", "Programado"), ("en_curso", "En curso"), ("finalizado", "Finalizado")],
        'filtros': {'equipo': equipo_id, 'campeonato': campeonato_id, 'estado': estado},
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def detalle_partido(request, pk):
    partido = get_object_or_404(Partido, pk=pk)
    sets = []
    for i in range(1, 6):
        local = getattr(partido, f"set{i}_local")
        externo = getattr(partido, f"set{i}_externo")
        if local is not None and externo is not None:
            sets.append((i, local, externo))
    return render(request, 'partidos/detalle_partido.html', {'partido': partido, 'sets': sets})


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def editar_partido(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    sets_con_datos = 1
    if request.method == 'POST':
        form = PartidoForm(request.POST, instance=partido)
        for i in range(1, 6):
            if request.POST.get(f"set{i}_local") or request.POST.get(f"set{i}_externo"):
                sets_con_datos = i
        if form.is_valid():
            partido = form.save(commit=False)
            partido.ganador = form.cleaned_data.get("ganador")
            partido.save()
            return redirect('lista_partidos')
    else:
        form = PartidoForm(instance=partido)
        for i in range(1, 6):
            if getattr(partido, f"set{i}_local") is not None or getattr(partido, f"set{i}_externo") is not None:
                sets_con_datos = i
    return render(request, 'partidos/editar_partido.html', {
        'form': form, 'partido': partido, 'sets_con_datos': sets_con_datos,
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def eliminar_partido(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if request.method == 'POST':
        partido.delete()
        return redirect('lista_partidos')
    return render(request, 'partidos/eliminar_partido.html', {'partido': partido})


# ─── Estadísticas ─────────────────────────────────────────────────────────────
# (Todas sin cambios respecto al original)

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
@require_http_methods(["GET", "POST"])
def agregar_estadistica(request, atleta_id):
    atleta = get_object_or_404(Atleta, id=atleta_id)
    mensaje_info = ""
    equipos = Equipo.objects.filter(atletas=atleta)

    if request.method == 'POST':
        form = EstadisticaForm(request.POST, atleta=atleta)
        if equipos.exists():
            partidos_disponibles = Partido.objects.filter(equipo_local__in=equipos).exclude(
                estadisticas__atleta=atleta).distinct()
            if not partidos_disponibles.exists():
                mensaje_info = "Este atleta ya tiene estadísticas en todos los partidos disponibles."
            form.fields['partido'].queryset = partidos_disponibles
        else:
            mensaje_info = "Este atleta aún no pertenece a ningún equipo."
        if form.is_valid():
            estadistica = form.save(commit=False)
            estadistica.atleta = atleta
            estadistica.save()
            return redirect('ver_estadisticas', atleta_id=atleta.id)
    else:
        form = EstadisticaForm(atleta=atleta)
        if equipos.exists():
            partidos_disponibles = Partido.objects.filter(equipo_local__in=equipos).exclude(
                estadisticas__atleta=atleta).distinct()
            if not partidos_disponibles.exists():
                mensaje_info = "Este atleta ya tiene estadísticas en todos los partidos disponibles."
            form.fields['partido'].queryset = partidos_disponibles
        else:
            mensaje_info = "Este atleta aún no pertenece a ningún equipo."

    return render(request, 'estadisticas/agregar_estadistica.html', {
        'form': form, 'atleta': atleta, 'mensaje_info': mensaje_info,
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u) or es_atleta(u))
def ver_estadisticas(request, atleta_id):
    atleta = get_object_or_404(Atleta, id=atleta_id)
    estadisticas_qs = Estadistica.objects.filter(atleta=atleta)
    mes = request.GET.get("mes")
    año = request.GET.get("año")
    if mes:
        estadisticas_qs = estadisticas_qs.filter(partido__fecha__month=int(mes))
    if año:
        estadisticas_qs = estadisticas_qs.filter(partido__fecha__year=int(año))
    estadisticas_qs = estadisticas_qs.order_by('-partido__fecha')
    paginator = Paginator(estadisticas_qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    años_disponibles = Estadistica.objects.filter(atleta=atleta).annotate(
        año=ExtractYear('partido__fecha')
    ).values_list('año', flat=True).distinct().order_by('-año')
    totales = estadisticas_qs.aggregate(
        puntos=Sum('puntos'), saques=Sum('saques'), remates=Sum('remates'),
        bloqueos=Sum('bloqueos'), armadas=Sum('armadas'), recepciones=Sum('recepciones'), errores=Sum('errores'),
    )
    meses = [(str(i), date(1900, i, 1).strftime('%B')) for i in range(1, 13)]
    return render(request, 'estadisticas/ver_estadisticas.html', {
        'atleta': atleta, 'page_obj': page_obj, 'totales': totales,
        'es_entrenador': es_entrenador(request.user),
        'default_year': date.today().year, 'meses': meses, 'años_disponibles': años_disponibles,
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def editar_estadistica(request, pk):
    estadistica = get_object_or_404(Estadistica, pk=pk)
    atleta = estadistica.atleta
    partidos_validos = Partido.objects.filter(equipo_local__in=atleta.equipo_set.all()).distinct()
    if request.method == 'POST':
        form = EstadisticaForm(request.POST, instance=estadistica)
        form.fields['partido'].queryset = partidos_validos
        if form.is_valid():
            form.save()
            return redirect('ver_estadisticas', atleta_id=atleta.id)
    else:
        form = EstadisticaForm(instance=estadistica)
        form.fields['partido'].queryset = partidos_validos.union(
            Partido.objects.filter(id=estadistica.partido.id))
    return render(request, 'estadisticas/editar_estadistica.html', {'form': form, 'estadistica': estadistica})


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def eliminar_estadistica(request, pk):
    estadistica = get_object_or_404(Estadistica, pk=pk)
    if request.method == 'POST':
        atleta_id = estadistica.atleta.id
        estadistica.delete()
        return redirect('ver_estadisticas', atleta_id=atleta_id)
    return render(request, 'estadisticas/eliminar_estadistica.html', {'estadistica': estadistica})


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u) or es_atleta(u))
def resumen_estadisticas(request, atleta_id):
    atleta = get_object_or_404(Atleta, id=atleta_id)
    estadisticas = Estadistica.objects.filter(atleta=atleta)
    if not estadisticas.exists():
        return render(request, 'estadisticas/resumen_estadisticas.html', {'atleta': atleta, 'sin_datos': True})
    datos = estadisticas.aggregate(
        puntos=Sum('puntos'), saques=Sum('saques'), remates=Sum('remates'),
        bloqueos=Sum('bloqueos'), armadas=Sum('armadas'), recepciones=Sum('recepciones'), errores=Sum('errores'),
    )
    hay_estadisticas = any([datos['puntos'], datos['saques'], datos['remates'], datos['bloqueos'], datos['armadas'], datos['recepciones']])

    def normalizar(valor, maximo=50):
        return min(round(((valor or 0) / maximo) * 100), 10000000)

    radar_datos = {
        'Remates': datos['remates'], 'Bloqueo': datos['bloqueos'],
        'Recepción': datos['recepciones'], 'Armada': datos['armadas'], 'Saques': datos['saques'],
    }
    radar_labels = list(radar_datos.keys())
    radar_values = [normalizar(v) for v in radar_datos.values()]
    puntos_neto = max((datos['puntos'] or 0) - (datos['errores'] or 0), 0)
    acciones_totales = sum([(datos[k] or 0) for k in datos]) or 1
    aportes = (datos['armadas'] or 0) + (datos['recepciones'] or 0)
    relacion_apoyo = round(min((aportes / acciones_totales) * 100, 100), 2)
    colores = {'Remates': '#e74c3c', 'Bloqueo': '#8e44ad', 'Recepción': '#27ae60', 'Armada': '#f39c12', 'Saques': '#3498db'}
    mayor = max(radar_datos, key=radar_datos.get)
    menor = min(radar_datos, key=radar_datos.get)
    leyendas = {
        'Remates': "El atleta se destaca en el Remate, siendo letal en situaciones ofensivas.",
        'Bloqueo': "El atleta posee gran capacidad para detener ataques rivales mediante Bloqueos.",
        'Recepción': "El atleta muestra confiabilidad en la Recepción, permitiendo jugadas organizadas.",
        'Armada': "El atleta es clave en Armar jugadas, facilitando la ofensiva del equipo.",
        'Saques': "El atleta demuestra gran efectividad al iniciar jugadas con el Saque.",
    }
    return render(request, 'estadisticas/resumen_estadisticas.html', {
        'atleta': atleta, 'datos': datos, 'puntos_neto': puntos_neto,
        'relacion_apoyo': relacion_apoyo, 'aportes': aportes,
        'radar_labels': radar_labels, 'radar_values': radar_values,
        'color_destacado': colores.get(mayor, 'rgba(54,162,235,0.6)'),
        'leyenda_mayor': leyendas.get(mayor, ''),
        'leyenda_menor': f"En cambio, <strong>{menor}</strong> representa su área más baja de rendimiento.",
        'hay_estadisticas': hay_estadisticas,
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def estadisticas_individuales(request):
    categoria_filtro = request.GET.get('categoria', '')
    cedula_filtro = request.GET.get('cedula', '')
    atletas_qs = Estadistica.objects.values(
        'atleta__id', 'atleta__nombre', 'atleta__apellido', 'atleta__cedula', 'atleta__categoria'
    ).annotate(
        puntos=Sum('puntos'), saques=Sum('saques'), remates=Sum('remates'),
        bloqueos=Sum('bloqueos'), recepciones=Sum('recepciones'), armadas=Sum('armadas'), errores=Sum('errores'),
    ).filter(Q(puntos__gt=0) | Q(saques__gt=0) | Q(remates__gt=0) | Q(bloqueos__gt=0) | Q(recepciones__gt=0) | Q(armadas__gt=0) | Q(errores__gt=0))
    if categoria_filtro:
        atletas_qs = atletas_qs.filter(atleta__categoria=categoria_filtro)
    if cedula_filtro:
        atletas_qs = atletas_qs.filter(atleta__cedula__icontains=cedula_filtro)
    paginator = Paginator(atletas_qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    categorias = Atleta.objects.values_list('categoria', flat=True).distinct().order_by('categoria')
    return render(request, 'estadisticas/estadisticas_individuales.html', {
        'estadisticas': page_obj, 'page_obj': page_obj,
        'categorias': categorias,
        'valores': {'categoria': categoria_filtro, 'cedula': cedula_filtro},
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def agregar_estadistica_general(request):
    atleta_encontrado = None
    estadistica_form = None
    mensaje_info = ""
    cedula = request.GET.get('cedula', '')

    if cedula and request.method == 'GET':
        try:
            atleta_encontrado = Atleta.objects.get(cedula=cedula)
            equipos = Equipo.objects.filter(atletas=atleta_encontrado)
            estadistica_form = EstadisticaForm(atleta=atleta_encontrado)
            if equipos.exists():
                partidos_disponibles = Partido.objects.filter(equipo_local__in=equipos).exclude(
                    estadisticas__atleta=atleta_encontrado).distinct()
                if not partidos_disponibles.exists():
                    mensaje_info = "Este atleta ya tiene estadísticas en todos los partidos disponibles."
                estadistica_form.fields['partido'].queryset = partidos_disponibles
            else:
                mensaje_info = "Este atleta aún no pertenece a ningún equipo."
        except Atleta.DoesNotExist:
            messages.error(request, "No se encontró ningún atleta con esa cédula.")
            estadistica_form = EstadisticaForm()

    if request.method == 'POST':
        atleta = get_object_or_404(Atleta, id=request.POST.get('atleta_id'))
        equipos = Equipo.objects.filter(atletas=atleta)
        estadistica_form = EstadisticaForm(request.POST, atleta=atleta)
        if equipos.exists():
            partidos_disponibles = Partido.objects.filter(equipo_local__in=equipos).exclude(
                estadisticas__atleta=atleta).distinct()
            estadistica_form.fields['partido'].queryset = partidos_disponibles
            if not partidos_disponibles.exists():
                mensaje_info = "Este atleta ya tiene estadísticas en todos los partidos disponibles."
        else:
            mensaje_info = "Este atleta aún no pertenece a ningún equipo."
        if estadistica_form.is_valid():
            est = estadistica_form.save(commit=False)
            est.atleta = atleta
            est.save()
            return redirect('estadisticas_individuales')
        else:
            messages.error(request, 'Error al registrar la estadística.')
        atleta_encontrado = atleta

    return render(request, 'estadisticas/agregar_estadistica_general.html', {
        'estadistica_form': estadistica_form or EstadisticaForm(),
        'atleta_encontrado': atleta_encontrado,
        'cedula': cedula, 'mensaje_info': mensaje_info,
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def ver_estadisticas_equipos(request):
    equipo_filtrado = request.GET.get('equipo')
    equipos = Equipo.objects.all()
    if equipo_filtrado:
        equipos = equipos.filter(id=equipo_filtrado)
    equipos_con_estadisticas = []
    for equipo in equipos:
        atletas = equipo.atletas.all()
        partidos_del_equipo = Partido.objects.filter(equipo_local=equipo)
        estadisticas = Estadistica.objects.filter(atleta__in=atletas, partido__in=partidos_del_equipo)
        totales = estadisticas.aggregate(
            puntos=Sum('puntos'), saques=Sum('saques'), remates=Sum('remates'),
            bloqueos=Sum('bloqueos'), armadas=Sum('armadas'), recepciones=Sum('recepciones'), errores=Sum('errores'),
        )
        if estadisticas.exists():
            equipos_con_estadisticas.append({'equipo': equipo, 'totales': totales})
    paginator = Paginator(equipos_con_estadisticas, 10)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, 'estadisticas/estadisticas_equipo.html', {
        'page_obj': page_obj, 'todos_equipos': Equipo.objects.all(),
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def ver_estadisticas_equipo_detalle(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    atletas = equipo.atletas.all()
    partido_id = request.GET.get('partido')
    mes = request.GET.get('mes')
    partidos_del_equipo = Partido.objects.filter(equipo_local=equipo)
    if partido_id:
        partidos_del_equipo = partidos_del_equipo.filter(id=partido_id)
    if mes:
        partidos_del_equipo = partidos_del_equipo.filter(fecha__month=mes)
    partidos_del_equipo = partidos_del_equipo.order_by('-fecha')
    estadisticas_por_partido = []
    for partido in partidos_del_equipo:
        estadisticas = Estadistica.objects.filter(atleta__in=atletas, partido=partido)
        resumen = estadisticas.aggregate(
            puntos=Sum('puntos'), saques=Sum('saques'), remates=Sum('remates'),
            bloqueos=Sum('bloqueos'), armadas=Sum('armadas'), recepciones=Sum('recepciones'), errores=Sum('errores'),
        )
        estadisticas_por_partido.append({'partido': partido, 'resumen': resumen})
    paginator = Paginator(estadisticas_por_partido, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    totales = Estadistica.objects.filter(atleta__in=atletas, partido__in=partidos_del_equipo).aggregate(
        puntos=Sum('puntos'), saques=Sum('saques'), remates=Sum('remates'),
        bloqueos=Sum('bloqueos'), armadas=Sum('armadas'), recepciones=Sum('recepciones'), errores=Sum('errores'),
    )
    meses = [(i, calendar.month_name[i]) for i in range(1, 13)]
    return render(request, 'estadisticas/ver_estadisticas_equipo_detalle.html', {
        'equipo': equipo, 'page_obj': page_obj, 'totales': totales,
        'partidos_disponibles': Partido.objects.filter(equipo_local=equipo).order_by('-fecha'),
        'meses': meses, 'es_entrenador': es_entrenador(request.user),
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def resumen_estadisticas_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    atletas = equipo.atletas.all()
    partidos_del_equipo = Partido.objects.filter(equipo_local=equipo)
    resumen_por_atleta = []
    for atleta in atletas:
        stats = Estadistica.objects.filter(atleta=atleta, partido__in=partidos_del_equipo)
        totales = stats.aggregate(
            puntos=Sum('puntos'), saques=Sum('saques'), remates=Sum('remates'),
            bloqueos=Sum('bloqueos'), armadas=Sum('armadas'), recepciones=Sum('recepciones'), errores=Sum('errores'),
        )
        resumen_por_atleta.append({'atleta': atleta, 'totales': totales})
    return render(request, 'estadisticas/resumen_equipo.html', {
        'equipo': equipo, 'resumen_por_atleta': resumen_por_atleta,
    })


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def resumen_estadisticas_equipo_grafico(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    atletas = equipo.atletas.all()
    estadisticas = Estadistica.objects.filter(
        atleta__in=atletas,
        partido__in=Partido.objects.filter(equipo_local=equipo)
    )
    if not estadisticas.exists():
        return render(request, 'estadisticas/resumen_equipo_grafico.html', {'equipo': equipo, 'sin_datos': True})
    datos = estadisticas.aggregate(
        puntos=Sum('puntos'), saques=Sum('saques'), remates=Sum('remates'),
        bloqueos=Sum('bloqueos'), armadas=Sum('armadas'), recepciones=Sum('recepciones'), errores=Sum('errores'),
    )

    def normalizar(valor, maximo=200):
        return min(round(((valor or 0) / maximo) * 100), 1000000)

    radar_datos = {
        'Remates': datos['remates'], 'Bloqueo': datos['bloqueos'],
        'Recepción': datos['recepciones'], 'Armada': datos['armadas'], 'Saques': datos['saques'],
    }
    mayor = max(radar_datos, key=radar_datos.get)
    menor = min(radar_datos, key=radar_datos.get)
    colores = {'Remates': '#e74c3c', 'Bloqueo': '#8e44ad', 'Recepción': '#27ae60', 'Armada': '#f39c12', 'Saques': '#3498db'}
    leyendas = {
        'Remates': "El equipo destaca en Remates, mostrando potencia ofensiva.",
        'Bloqueo': "Gran capacidad defensiva en Bloqueos, conteniendo ataques rivales.",
        'Recepción': "Recepciones consistentes que permiten fluidez en el juego.",
        'Armada': "Alta participación en Armadas, clave para organizar jugadas.",
        'Saques': "Buena efectividad en Saques para iniciar jugadas.",
    }
    acciones_totales = sum([(datos[k] or 0) for k in datos]) or 1
    aportes = (datos['armadas'] or 0) + (datos['recepciones'] or 0)
    return render(request, 'estadisticas/resumen_equipo_grafico.html', {
        'equipo': equipo, 'datos': datos,
        'puntos_neto': max((datos['puntos'] or 0) - (datos['errores'] or 0), 0),
        'relacion_apoyo': round(min((aportes / acciones_totales) * 100, 100), 2),
        'aportes': aportes,
        'radar_labels': list(radar_datos.keys()),
        'radar_values': [normalizar(v) for v in radar_datos.values()],
        'color_destacado': colores.get(mayor, 'rgba(54,162,235,0.6)'),
        'leyenda_mayor': leyendas.get(mayor, ''),
        'leyenda_menor': f"En cambio, <strong>{menor}</strong> es su punto más bajo, indicando un área de mejora.",
    })


# ─── Reportes (sin cambios) ───────────────────────────────────────────────────
# Las vistas de reportes son idénticas al archivo original.
# Se omiten aquí para brevedad; copiar del archivo atletas/views.py original
# desde `reporte_pagos_view` hasta el final.
# ─────────────────────────────────────────────────────────────────────────────
# NOTE: paste the original report views here unchanged
def parse_fecha(fecha_str):
    if not fecha_str:
        return None
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(fecha_str, fmt).date()
        except ValueError:
            continue
    return None


def aplicar_filtros(request):
    atletas = Atleta.objects.all()
    cedula = request.GET.get('cedula', '').strip()
    nombre = request.GET.get('nombre', '').strip()
    categoria = request.GET.get('categoria', '')
    edad_min = request.GET.get('edad_min')
    edad_max = request.GET.get('edad_max')
    sexo = request.GET.get('sexo', '')
    if cedula:
        atletas = atletas.filter(cedula__icontains=cedula)
    if nombre:
        atletas = atletas.filter(nombre__icontains=nombre) | atletas.filter(apellido__icontains=nombre)
    if categoria:
        atletas = atletas.filter(categoria=categoria)
    if edad_min:
        atletas = atletas.filter(fecha_nacimiento__year__lte=date.today().year - int(edad_min))
    if edad_max:
        atletas = atletas.filter(fecha_nacimiento__year__gte=date.today().year - int(edad_max))
    if sexo:
        atletas = atletas.filter(sexo__iexact=sexo)
    return atletas


# (El resto de las vistas de reportes se copia sin cambios del original)
# reporte_pagos_view, exportar_pagos_excel, exportar_pagos_pdf,
# reporte_atletas_view, reporte_atletas_excel, reporte_atletas_pdf,
# reporte_estadisticas, exportar_estadisticas_pdf,
# reporte_estadisticas_equipo, exportar_estadisticas_equipo_pdf,
# reporte_equipos, exportar_equipo_pdf,
# reporte_entrenadores_view, reporte_entrenadores_excel, reporte_entrenadores_pdf,
# reporte_campeonatos, reporte_campeonatos_pdf, reporte_campeonatos_excel,
# reporte_partidos, exportar_partidos_pdf, exportar_partidos_excel
# → Copiar del archivo original sin ningún cambio.
