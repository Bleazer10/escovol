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
matplotlib.use('Agg')  # Usa backend sin GUI
import matplotlib.pyplot as plt
from reportlab.lib.units import inch
from collections import defaultdict
import numpy as np
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from openpyxl.styles import Font, Alignment, PatternFill,  Border, Side
from openpyxl.utils import get_column_letter
from django.db.models import Prefetch
from django.utils.dateparse import parse_date
from django.utils.encoding import escape_uri_path
from .utils.roles import es_admin, es_entrenador, es_atleta
from django.contrib import admin
from django.contrib.auth.hashers import make_password
from .services import crear_usuario_para_atleta, crear_usuario_para_administrador, crear_usuario_para_entrenador

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
    
    # paginar
    from django.core.paginator import Paginator
    paginator = Paginator(atletas, 8)
    page_number = request.GET.get('page')
    atletas = paginator.get_page(page_number)

    # para los selects
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
            # Guardar atleta sin usuario todavía
            atleta = atleta_form.save(commit=False)

            # Datos del usuario
            username = usuario_form.cleaned_data['username']
            password = usuario_form.cleaned_data['password']
            email = usuario_form.cleaned_data['email']

            # Crear usuario + asignar grupo automáticamente
            crear_usuario_para_atleta(atleta, username, password, email)

            return redirect('lista_atletas')
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
        # Si el usuario es un atleta y no es el dueño del perfil, redirigir
        return redirect('bienvenida')

    # ✅ Calcular despegue si aplica
    despegue = None
    if atleta.salto is not None and atleta.alcance is not None:
        despegue = round((atleta.salto - atleta.alcance) * 100, 2)

    context = {
        'atleta': atleta,
        'despegue': despegue,
    }
    return render(request, 'atletas/detalle_atleta.html', context)


@user_passes_test(es_admin)
def editar_atleta(request, atleta_id):
    atleta = get_object_or_404(Atleta, id=atleta_id)
    usuario = getattr(atleta, "user", None)

    if request.method == 'POST':
        form = AtletaForm(request.POST, instance=atleta)
        usuario_form = UsuarioForm(request.POST, instance=usuario)  # 🔑 siempre creamos el form

        if form.is_valid() and usuario_form.is_valid():
            form.save()
            user = usuario_form.save(commit=False)

            # Si es un usuario nuevo, hay que asignarle username obligatorio
            if not usuario:
                user.username = form.cleaned_data['cedula']  # por ejemplo, usar la cédula
                user.set_password(usuario_form.cleaned_data['password'])

            else:
                # Si ya existía, solo cambiamos password si vino algo nuevo
                password = usuario_form.cleaned_data.get("password")
                if password:
                    user.set_password(password)

            user.save()
            # Asegurar que el atleta quede vinculado con este usuario
            atleta.user = user
            atleta.save()

            return redirect('detalle_atleta', atleta_id=atleta.id)
    else:
        form = AtletaForm(instance=atleta)
        usuario_form = UsuarioForm(instance=usuario)  # 🔑 siempre creamos el form

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

    # Filtrar atletas
    atletas = Atleta.objects.all()
    if categoria_filtro:
        atletas = atletas.filter(categoria=categoria_filtro)

    # Asegurar que existan mensualidades para el año actual y siguiente
    for atleta in atletas:
        for mes in range(1, 13):
            Mensualidad.objects.get_or_create(
                atleta=atleta,
                mes=mes,
                año=año_actual,
                defaults={"monto_pagado": 0.00, "exonerado": False}
            )

    siguiente_año = año_actual + 1
    for atleta in atletas:
        for mes in range(1, 13):
            Mensualidad.objects.get_or_create(
                atleta=atleta,
                mes=mes,
                año=siguiente_año,
                defaults={"monto_pagado": 0.00, "exonerado": False}
            )

    # Preparar registros para la tabla
    registros = []
    for atleta in atletas:
        mensualidad = Mensualidad.objects.filter(
            atleta=atleta, mes=mes_filtro, año=año_actual
        ).first()
        registros.append({
            "atleta": atleta,
            "mensualidad": mensualidad
        })

    # ✅ Cálculos del resumen mensual
    mensualidades_mes = Mensualidad.objects.filter(mes=mes_filtro, año=año_actual)
    if categoria_filtro:
        mensualidades_mes = mensualidades_mes.filter(atleta__categoria=categoria_filtro)

    total_recaudado = mensualidades_mes.aggregate(total=Sum("monto_pagado"))["total"] or 0
    total_atletas = mensualidades_mes.count()

    al_dia = 0
    exonerados = 0
    for m in mensualidades_mes:
        if m.estado() == "Al día":
            al_dia += 1
        elif m.estado() == "Exonerado":
            exonerados += 1

    deudores = total_atletas - al_dia - exonerados

    # Paginación
    paginator = Paginator(registros, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Meses y categorías para filtros
    meses = [(i, date(1900, i, 1).strftime('%B')) for i in range(1, 13)]
    categorias = Atleta.objects.values_list("categoria", flat=True).distinct()

    context = {
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
    }

    return render(request, 'atletas/administracion.html', context)

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def lista_entrenadores(request):
    entrenadores = Entrenador.objects.all().order_by('nombre')  # o el orden que prefieras

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
def editar_entrenador(request, entrenador_id):
    entrenador = get_object_or_404(Entrenador, id=entrenador_id)
    usuario = getattr(entrenador, "user", None)  # relación OneToOne, puede ser None

    if request.method == 'POST':
        form = EntrenadorForm(request.POST, instance=entrenador)
        usuario_form = UsuarioForm(request.POST, instance=usuario)  # 👈 siempre

        if form.is_valid() and usuario_form.is_valid():
            form.save()

            # Guardar usuario
            usuario = usuario_form.save(commit=False)

            # Si se ingresó nueva contraseña
            new_password = usuario_form.cleaned_data.get("password")
            if new_password:
                usuario.set_password(new_password)

            usuario.save()

            # Asegurar la relación si no existía
            if not entrenador.user:
                entrenador.user = usuario
                entrenador.save()

            return redirect('detalle_entrenador', entrenador_id=entrenador.id)

    else:
        form = EntrenadorForm(instance=entrenador)
        usuario_form = UsuarioForm(instance=usuario)  # 👈 siempre

    return render(request, 'entrenadores/editar_entrenador.html', {
        'form': form,
        'usuario_form': usuario_form,
        'entrenador': entrenador
    })


@user_passes_test(es_admin)
def eliminar_entrenador(request, entrenador_id):
    entrenador = get_object_or_404(Entrenador, id=entrenador_id)
    if request.method == 'POST':
        entrenador.delete()
        messages.success(request, 'Entrenador eliminado con éxito.')
        return redirect('lista_entrenadores')
    context = {
        'entrenador': entrenador
    }
    return render(request, 'entrenadores/eliminar_entrenador.html', context)

@user_passes_test(es_admin)
def registrar_entrenador(request):
    if request.method == 'POST':
        usuario_form = UsuarioForm(request.POST)
        entrenador_form = EntrenadorForm(request.POST)

        if usuario_form.is_valid() and entrenador_form.is_valid():
            # Guardar entrenador sin usuario aún
            entrenador = entrenador_form.save(commit=False)

            # Datos del usuario
            username = usuario_form.cleaned_data['username']
            password = usuario_form.cleaned_data['password']
            email = usuario_form.cleaned_data['email']

            # Crear usuario + asignar grupo automáticamente
            crear_usuario_para_entrenador(entrenador, username, password, email)

            return redirect('lista_entrenadores')
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
    usuario = getattr(entrenador, "user", None)  # si no tiene usuario, será None

    return render(request, 'entrenadores/detalle_entrenador.html', {
        'entrenador': entrenador,
        'usuario': usuario,
    })

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def registrar_campeonato(request):
    if request.method == 'POST':
        form = CampeonatoForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('lista_campeonatos')  # Cambia esto si la URL tiene otro nombre
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

    paginator = Paginator(campeonatos, 10)  # Número de campeonatos por página
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    valores = {
        'tipo': tipo,
        'anio': anio,
    }

    return render(request, 'campeonatos/lista_campeonatos.html', {
        'campeonatos': page_obj,  # <- este es el objeto paginado
        'page_obj': page_obj,     # <- este es necesario para la paginación
        'valores': valores,
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
    return render(request, 'campeonatos/editar_campeonato.html', {
        'form': form,
        'campeonato': campeonato
    })

# Vista para eliminar campeonato
@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def eliminar_campeonato(request, campeonato_id):
    campeonato = get_object_or_404(Campeonato, id=campeonato_id)
    if request.method == 'POST':
        campeonato.delete()
        return redirect('lista_campeonatos')
    return render(request, 'campeonatos/eliminar_campeonato.html', {
        'campeonato': campeonato
    })

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def detalle_campeonato(request, campeonato_id):
    campeonato = get_object_or_404(Campeonato, id=campeonato_id)
    return render(request, 'campeonatos/detalle_campeonato.html', {
        'campeonato': campeonato
    })

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
            todos = Atleta.objects.all()
            for atleta in todos:
                edad = calcular_edad(atleta.fecha_nacimiento)
                if edad <= edad_tope:
                    if sexo == 'mixto' or atleta.sexo == sexo:
                        atleta.edad = edad  # atributo temporal
                        atletas_filtrados.append(atleta)
            mostrar_formulario = True
        except ValueError:
            edad_tope = None

    if request.method == 'POST':
        form = EquipoForm(request.POST)
        atletas_ids = request.POST.getlist('atletas_seleccionados')

        # Validamos que no pasen de 14 atletas
        if len(atletas_ids) > 14:
            error_maximo = True
            mostrar_formulario = True  # Mantener el formulario visible
        elif form.is_valid():
            equipo = form.save(commit=False)
            equipo.sexo_equipo = sexo
            equipo.edad_tope = edad_tope
            equipo.save()
            equipo.atletas.set(atletas_ids)
            return redirect('listar_equipos')

    else:
        form = EquipoForm()

    context = {
        'form': form,
        'edad_tope': edad_tope,
        'sexo': sexo,
        'atletas_disponibles': atletas_filtrados,
        'atletas_seleccionados': request.POST.getlist('atletas_seleccionados') if request.method == 'POST' else [],
        'mostrar_formulario': mostrar_formulario,
        'error_maximo': error_maximo
    }
    return render(request, 'equipos/registrar_equipo.html', context)


# Vista para listar equipos
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
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'entrenadores': Entrenador.objects.all(),
        'valores': {
            'nombre': nombre,
            'entrenador': entrenador_id,
        }
    }
    return render(request, 'equipos/listar_equipos.html', context)

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def detalle_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, pk=equipo_id)
    atletas = equipo.atletas.all().order_by('nombre')

    # Calcular edad para cada atleta
    for atleta in atletas:
        atleta.edad = calcular_edad(atleta.fecha_nacimiento)

    return render(request, 'equipos/detalle_equipo.html', {
        'equipo': equipo,
        'atletas': atletas
    })

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def eliminar_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, pk=equipo_id)

    if request.method == 'POST':
        nombre = equipo.nombre
        equipo.delete()
        return redirect('listar_equipos')

    return render(request, 'equipos/eliminar_equipo.html', {'equipo': equipo})


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def editar_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, pk=equipo_id)
    error_msg = None
    atletas_filtrados = []
    atletas_ids = []

    # Obtener sexo del equipo original (campo fijo)
    # Al inicio
    sexo = request.POST.get('sexo_equipo') or request.GET.get('sexo') or equipo.sexo_equipo


    # Obtener edad tope desde GET, POST o calcular según atletas actuales
    # Obtener edad_tope como string
    edad_tope = request.GET.get('edad_tope') or request.POST.get('edad_tope')

    # Si no hay edad_tope enviada, usar la que se guardó en el modelo
    if not edad_tope:
        if equipo.edad_tope:
            edad_tope = equipo.edad_tope
        elif equipo.atletas.exists():
            edad_tope = max([calcular_edad(a.fecha_nacimiento) for a in equipo.atletas.all()])
        else:
            edad_tope = ''

    # Validar edad_tope
    error_msg = None
    try:
        edad_tope_int = int(edad_tope)
        if edad_tope_int <= 0:
            raise ValueError
    except ValueError:
        edad_tope_int = None
        error_msg = "Edad tope inválida."

    # Si la edad_tope es válida, filtrar atletas
    if edad_tope_int:
        atletas_filtrados = []
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
            equipo.sexo_equipo = sexo  # Se mantiene sin editar
            equipo.edad_tope = edad_tope_int
            equipo.save()
            equipo.atletas.set(atletas_ids)
            return redirect('detalle_equipo', equipo.id)
    else:
        form = EquipoForm(instance=equipo)
        atletas_ids = list(equipo.atletas.values_list('id', flat=True))

    context = {
        'form': form,
        'equipo': equipo,
        'sexo': sexo,
        'edad_tope': edad_tope,
        'atletas_disponibles': atletas_filtrados,
        'atletas_seleccionados': atletas_ids,
        'error_msg': error_msg,
        'mostrar_formulario': True  # Siempre mostrar el formulario
    }
    return render(request, 'equipos/editar_equipo.html', context)

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def registrar_partido(request):
    sets_con_datos = 1

    seis_meses_atras = timezone.now() - timedelta(days=180)
    campeonatos_recientes = Campeonato.objects.filter(fecha_inicio__gte=seis_meses_atras)

    if request.method == 'POST':
        form = PartidoForm(request.POST)

        # ✅ aplicar queryset también en POST
        form.fields['campeonato'].queryset = campeonatos_recientes

        for i in range(1, 6):
            local = request.POST.get(f"set{i}_local")
            externo = request.POST.get(f"set{i}_externo")
            if local or externo:
                sets_con_datos = i

        if form.is_valid():
            partido = form.save(commit=False)

            # ✅ usar el ganador calculado por el form (no recalcular aquí)
            partido.ganador = form.cleaned_data.get("ganador")

            partido.save()
            return redirect('lista_partidos')
    else:
        form = PartidoForm()
        form.fields['campeonato'].queryset = campeonatos_recientes  # ✅ en GET también

    return render(request, 'partidos/registrar_partido.html', {
        'form': form,
        'sets_con_datos': sets_con_datos
    })

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def lista_partidos(request):
    partidos = Partido.objects.order_by('-fecha', '-hora')

    # Obtener parámetros de filtro
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
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Pasar opciones de selects al template
    equipos = Equipo.objects.order_by('nombre')
    campeonatos = Campeonato.objects.order_by('-fecha_inicio')
    estados = [
        ("programado", "Programado"),
        ("en_curso", "En curso"),
        ("finalizado", "Finalizado"),
    ]

    context = {
        'page_obj': page_obj,
        'equipos': equipos,
        'campeonatos': campeonatos,
        'estados': estados,
        'filtros': {
            'equipo': equipo_id,
            'campeonato': campeonato_id,
            'estado': estado,
        }
    }
    return render(request, 'partidos/lista_partidos.html', context)

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def detalle_partido(request, pk):
    partido = get_object_or_404(Partido, pk=pk)
    sets = []
    for i in range(1, 6):
        local = getattr(partido, f"set{i}_local")
        externo = getattr(partido, f"set{i}_externo")
        if local is not None and externo is not None:
            sets.append((i, local, externo))
    return render(request, 'partidos/detalle_partido.html', {
        'partido': partido,
        'sets': sets
    })

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def editar_partido(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    sets_con_datos = 1

    if request.method == 'POST':
        form = PartidoForm(request.POST, instance=partido)

        for i in range(1, 6):
            local = request.POST.get(f"set{i}_local")
            externo = request.POST.get(f"set{i}_externo")
            if local or externo:
                sets_con_datos = i

        if form.is_valid():
            partido = form.save(commit=False)

            # ✅ usar ganador calculado por el form
            partido.ganador = form.cleaned_data.get("ganador")

            partido.save()
            return redirect('lista_partidos')
    else:
        form = PartidoForm(instance=partido)

        for i in range(1, 6):
            local = getattr(partido, f"set{i}_local")
            externo = getattr(partido, f"set{i}_externo")
            if local is not None or externo is not None:
                sets_con_datos = i

    return render(request, 'partidos/editar_partido.html', {
        'form': form,
        'partido': partido,
        'sets_con_datos': sets_con_datos,
    })

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def eliminar_partido(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if request.method == 'POST':
        partido.delete()
        return redirect('lista_partidos')
    return render(request, 'partidos/eliminar_partido.html', {'partido': partido})

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
@require_http_methods(["GET", "POST"])
def agregar_estadistica(request, atleta_id):
    atleta = get_object_or_404(Atleta, id=atleta_id)
    mensaje_info = ""

    if request.method == 'POST':
        form = EstadisticaForm(request.POST, atleta=atleta)

        # Buscar todos los equipos donde esté el atleta
        equipos = Equipo.objects.filter(atletas=atleta)

        if equipos.exists():
            partidos_equipo = Partido.objects.filter(equipo_local__in=equipos)
            partidos_disponibles = partidos_equipo.exclude(
                estadisticas__atleta=atleta
            ).distinct()

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

        equipos = Equipo.objects.filter(atletas=atleta)

        if equipos.exists():
            partidos_equipo = Partido.objects.filter(equipo_local__in=equipos)
            partidos_disponibles = partidos_equipo.exclude(
                estadisticas__atleta=atleta
            ).distinct()

            if not partidos_disponibles.exists():
                mensaje_info = "Este atleta ya tiene estadísticas en todos los partidos disponibles."

            form.fields['partido'].queryset = partidos_disponibles
        else:
            mensaje_info = "Este atleta aún no pertenece a ningún equipo."

    return render(request, 'estadisticas/agregar_estadistica.html', {
        'form': form,
        'atleta': atleta,
        'mensaje_info': mensaje_info,
    })

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u) or es_atleta(u))
def ver_estadisticas(request, atleta_id):
    atleta = get_object_or_404(Atleta, id=atleta_id)
    estadisticas_qs = Estadistica.objects.filter(atleta=atleta)

    # Filtros por mes y año
    mes = request.GET.get("mes")
    año = request.GET.get("año")

    if mes:
        estadisticas_qs = estadisticas_qs.filter(partido__fecha__month=int(mes))
    if año:
        estadisticas_qs = estadisticas_qs.filter(partido__fecha__year=int(año))

    # Ordenar por fecha descendente
    estadisticas_qs = estadisticas_qs.order_by('-partido__fecha')

    # Paginación
    paginator = Paginator(estadisticas_qs, 10)  # Cambia el número si quieres más filas por página
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Lista de años únicos con datos para mostrar en el selector
    años_disponibles = Estadistica.objects.filter(atleta=atleta).annotate(
        año=ExtractYear('partido__fecha')
    ).values_list('año', flat=True).distinct().order_by('-año')

    # Calcular totales (sin paginar)
    totales = estadisticas_qs.aggregate(
        puntos=Sum('puntos'),
        saques=Sum('saques'),
        remates=Sum('remates'),
        bloqueos=Sum('bloqueos'),
        armadas=Sum('armadas'),
        recepciones=Sum('recepciones'),
        errores=Sum('errores'),
    )

    meses = [(str(i), date(1900, i, 1).strftime('%B')) for i in range(1, 13)]

    context = {
        'atleta': atleta,
        'page_obj': page_obj,
        'totales': totales,
        'es_entrenador': es_entrenador(request.user),
        'default_year': date.today().year,
        'meses': meses,
        'años_disponibles': años_disponibles,
    }

    return render(request, 'estadisticas/ver_estadisticas.html', context)

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def editar_estadistica(request, pk):
    estadistica = get_object_or_404(Estadistica, pk=pk)
    atleta = estadistica.atleta

    # Obtener equipos a los que pertenece el atleta
    equipos_atleta = atleta.equipo_set.all()

    # Filtrar los partidos donde participa alguno de esos equipos
    partidos_validos = Partido.objects.filter(
        equipo_local__in=equipos_atleta
    ).distinct()

    if request.method == 'POST':
        form = EstadisticaForm(request.POST, instance=estadistica)
        form.fields['partido'].queryset = partidos_validos

        if form.is_valid():
            form.save()
            return redirect('ver_estadisticas', atleta_id=atleta.id)
    else:
        form = EstadisticaForm(instance=estadistica)
        # Aseguramos que el partido actual también esté incluido
        form.fields['partido'].queryset =  partidos_validos.union(
        Partido.objects.filter(id=estadistica.partido.id)
    )

    return render(request, 'estadisticas/editar_estadistica.html', {
        'form': form,
        'estadistica': estadistica,
    })

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def eliminar_estadistica(request, pk):
    estadistica = get_object_or_404(Estadistica, pk=pk)
    
    if request.method == 'POST':
        atleta_id = estadistica.atleta.id
        estadistica.delete()
        return redirect('ver_estadisticas', atleta_id=atleta_id)
    
    return render(request, 'estadisticas/eliminar_estadistica.html', {
        'estadistica': estadistica
    })

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u) or es_atleta(u))
def resumen_estadisticas(request, atleta_id):
    atleta = get_object_or_404(Atleta, id=atleta_id)
    estadisticas = Estadistica.objects.filter(atleta=atleta)

    # Si no hay estadísticas, mostrar un resumen vacío
    if not estadisticas.exists():
        context = {
            'atleta': atleta,
            'sin_datos': True,
        }
        return render(request, 'estadisticas/resumen_estadisticas.html', context)

    # Aseguramos que cada dato sea 0 si es None
    datos = estadisticas.aggregate(
        puntos=Sum('puntos') or 0,
        saques=Sum('saques') or 0,
        remates=Sum('remates') or 0,
        bloqueos=Sum('bloqueos') or 0,
        armadas=Sum('armadas') or 0,
        recepciones=Sum('recepciones') or 0,
        errores=Sum('errores') or 0,
    )

    # Nueva lógica: comprobar si al menos una estadística (excepto errores) tiene datos
    hay_estadisticas = any([
        datos['puntos'], datos['saques'], datos['remates'],
        datos['bloqueos'], datos['armadas'], datos['recepciones']
    ])

    def normalizar(valor, maximo=50):
        valor = valor or 0
        return min(round((valor / maximo) * 100), 10000000)
    
    radar_datos = {
        'Remates': datos['remates'],
        'Bloqueo': datos['bloqueos'],
        'Recepción': datos['recepciones'],
        'Armada': datos['armadas'],
        'Saques': datos['saques'],
    }

    radar_labels = list(radar_datos.keys())
    radar_values = [normalizar(valor) for valor in radar_datos.values()]

    puntos_neto = max(datos['puntos'] - datos['errores'], 0)
    acciones_totales = sum([
        datos['puntos'], datos['saques'],
        datos['remates'], datos['bloqueos'],
        datos['armadas'], datos['recepciones'],
        datos['errores'],
    ]) or 1

    aportes = datos['armadas'] + datos['recepciones']
    relacion_apoyo = round(min((aportes / acciones_totales) * 100, 100), 2)

    colores_caracteristicas = {
        'Remates': '#e74c3c',
        'Bloqueo': '#8e44ad',
        'Recepción': '#27ae60',
        'Armada': '#f39c12',
        'Saques': '#3498db',
    }

    mayor = max(radar_datos, key=radar_datos.get)
    menor = min(radar_datos, key=radar_datos.get)
    color_destacado = colores_caracteristicas.get(mayor, 'rgba(54, 162, 235, 0.6)')

    leyendas = {
        'Remates': "El atleta se destaca en el Remate, siendo letal en situaciones ofensivas.",
        'Bloqueo': "El atleta posee gran capacidad para detener ataques rivales mediante Bloqueos.",
        'Recepción': "El atleta muestra confiabilidad en la Recepción, permitiendo jugadas organizadas.",
        'Armada': "El atleta es clave en Armar jugadas, facilitando la ofensiva del equipo.",
        'Saques': "El atleta demuestra gran efectividad al iniciar jugadas con el Saque.",
    }

    leyenda_mayor = leyendas.get(mayor, "")
    leyenda_menor = (
        f"En cambio, <strong>{menor}</strong> representa su área más baja de rendimiento, "
        f"por lo que puede ser una oportunidad de mejora o entrenamiento específico."
    )

    context = {
        'atleta': atleta,
        'datos': datos,
        'puntos_neto': puntos_neto,
        'relacion_apoyo': relacion_apoyo,
        'aportes': aportes,
        'radar_labels': radar_labels,
        'radar_values': radar_values,
        'color_destacado': color_destacado,
        'leyenda_mayor': leyenda_mayor,
        'leyenda_menor': leyenda_menor,
        'hay_estadisticas': hay_estadisticas
    }

    return render(request, 'estadisticas/resumen_estadisticas.html', context)

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def estadisticas_individuales(request):
    categoria_filtro = request.GET.get('categoria', '')
    cedula_filtro = request.GET.get('cedula', '')

    atletas_qs = Estadistica.objects.values(
        'atleta__id', 'atleta__nombre', 'atleta__apellido', 'atleta__cedula', 'atleta__categoria'
    ).annotate(
        puntos=Sum('puntos'),
        saques=Sum('saques'),
        remates=Sum('remates'),
        bloqueos=Sum('bloqueos'),
        recepciones=Sum('recepciones'),
        armadas=Sum('armadas'),
        errores=Sum('errores')
    ).filter(
        Q(puntos__gt=0) |
        Q(saques__gt=0) |
        Q(remates__gt=0) |
        Q(bloqueos__gt=0) |
        Q(recepciones__gt=0) |
        Q(armadas__gt=0) |
        Q(errores__gt=0)
    )

    if categoria_filtro:
        atletas_qs = atletas_qs.filter(atleta__categoria=categoria_filtro)

    if cedula_filtro:
        atletas_qs = atletas_qs.filter(atleta__cedula__icontains=cedula_filtro)

    paginator = Paginator(atletas_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    categorias = Atleta.objects.values_list('categoria', flat=True).distinct().order_by('categoria')

    context = {
        'estadisticas': page_obj,
        'page_obj': page_obj,
        'categorias': categorias,
        'valores': {
            'categoria': categoria_filtro,
            'cedula': cedula_filtro,
        }
    }
    return render(request, 'estadisticas/estadisticas_individuales.html', context)
    
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

            if equipos.exists():
                # Obtener todos los partidos de todos los equipos
                partidos_equipo = Partido.objects.filter(equipo_local__in=equipos)

                # Excluir partidos donde ya tenga estadística
                partidos_disponibles = partidos_equipo.exclude(
                    estadisticas__atleta=atleta_encontrado
                ).distinct()

                if not partidos_disponibles.exists():
                    mensaje_info = "Este atleta ya tiene estadísticas en todos los partidos disponibles."

                estadistica_form = EstadisticaForm(atleta=atleta_encontrado)
                estadistica_form.fields['partido'].queryset = partidos_disponibles
            else:
                mensaje_info = "Este atleta aún no pertenece a ningún equipo."
                estadistica_form = EstadisticaForm()
        except Atleta.DoesNotExist:
            messages.error(request, "No se encontró ningún atleta con esa cédula.")
            estadistica_form = EstadisticaForm()

    if request.method == 'POST':
        atleta_id = request.POST.get('atleta_id')
        atleta = get_object_or_404(Atleta, id=atleta_id)
        equipos = Equipo.objects.filter(atletas=atleta)

        estadistica_form = EstadisticaForm(request.POST, atleta=atleta)

        if equipos.exists():
            partidos_equipo = Partido.objects.filter(equipo_local__in=equipos)
            partidos_disponibles = partidos_equipo.exclude(
                estadisticas__atleta=atleta
            ).distinct()

            estadistica_form.fields['partido'].queryset = partidos_disponibles

            if not partidos_disponibles.exists():
                mensaje_info = "Este atleta ya tiene estadísticas en todos los partidos disponibles."
        else:
            mensaje_info = "Este atleta aún no pertenece a ningún equipo."

        if estadistica_form.is_valid():
            estadistica = estadistica_form.save(commit=False)
            estadistica.atleta = atleta
            estadistica.save()
            return redirect('estadisticas_individuales')
        else:
            messages.error(request, 'Error al registrar la estadística.')

        atleta_encontrado = atleta

    context = {
        'estadistica_form': estadistica_form or EstadisticaForm(),
        'atleta_encontrado': atleta_encontrado,
        'cedula': cedula,
        'mensaje_info': mensaje_info,
    }
    return render(request, 'estadisticas/agregar_estadistica_general.html', context)


@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def ver_estadisticas_equipos(request):
    equipo_filtrado = request.GET.get('equipo')

    equipos = Equipo.objects.all()
    if equipo_filtrado:
        equipos = equipos.filter(id=equipo_filtrado)

    equipos_con_estadisticas = []
    for equipo in equipos:
        atletas = equipo.atletas.all()
        # Filtrar estadísticas solo de partidos donde el equipo participó
        partidos_del_equipo = Partido.objects.filter(equipo_local=equipo)

        estadisticas = Estadistica.objects.filter(
            atleta__in=atletas,
            partido__in=partidos_del_equipo
        )

        totales = estadisticas.aggregate(
            puntos=Sum('puntos'),
            saques=Sum('saques'),
            remates=Sum('remates'),
            bloqueos=Sum('bloqueos'),
            armadas=Sum('armadas'),
            recepciones=Sum('recepciones'),
            errores=Sum('errores'),
        )

        if estadisticas.exists():
            equipos_con_estadisticas.append({
                'equipo': equipo,
                'totales': totales,
            })

    paginator = Paginator(equipos_con_estadisticas, 10)  # 10 por página
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'todos_equipos': Equipo.objects.all(),
    }
    return render(request, 'estadisticas/estadisticas_equipo.html', context)

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def ver_estadisticas_equipo_detalle(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    atletas = equipo.atletas.all()

    # Obtener filtros
    partido_id = request.GET.get('partido')
    mes = request.GET.get('mes')

    # Obtener los partidos jugados por el equipo
    partidos_del_equipo = Partido.objects.filter(equipo_local=equipo)

    # Aplicar filtros
    if partido_id:
        partidos_del_equipo = partidos_del_equipo.filter(id=partido_id)
    if mes:
        partidos_del_equipo = partidos_del_equipo.filter(fecha__month=mes)

    partidos_del_equipo = partidos_del_equipo.order_by('-fecha')

    # Generar resumen por partido (acumulando estadísticas de sus atletas)
    estadisticas_por_partido = []
    for partido in partidos_del_equipo:
        estadisticas = Estadistica.objects.filter(
            atleta__in=atletas,
            partido=partido
        )

        resumen = estadisticas.aggregate(
            puntos=Sum('puntos'),
            saques=Sum('saques'),
            remates=Sum('remates'),
            bloqueos=Sum('bloqueos'),
            armadas=Sum('armadas'),
            recepciones=Sum('recepciones'),
            errores=Sum('errores'),
        )

        estadisticas_por_partido.append({
            'partido': partido,
            'resumen': resumen,
        })

    # Paginación
    paginator = Paginator(estadisticas_por_partido, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Totales acumulados del equipo (ajustados al filtro actual)
    totales = Estadistica.objects.filter(
        atleta__in=atletas,
        partido__in=partidos_del_equipo  # ya filtrado por mes y partido
    ).aggregate(
        puntos=Sum('puntos'),
        saques=Sum('saques'),
        remates=Sum('remates'),
        bloqueos=Sum('bloqueos'),
        armadas=Sum('armadas'),
        recepciones=Sum('recepciones'),
        errores=Sum('errores'),
    )


    # Filtros disponibles
    partidos_disponibles = Partido.objects.filter(equipo_local=equipo).order_by('-fecha')
    meses = [
        (1, "Enero"), (2, "Febrero"), (3, "Marzo"), (4, "Abril"),
        (5, "Mayo"), (6, "Junio"), (7, "Julio"), (8, "Agosto"),
        (9, "Septiembre"), (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre")
    ]

    context = {
        'equipo': equipo,
        'page_obj': page_obj,
        'totales': totales,
        'partidos_disponibles': partidos_disponibles,
        'meses': meses,
        'es_entrenador': es_entrenador(request.user),
    }

    return render(request, 'estadisticas/ver_estadisticas_equipo_detalle.html', context)

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def resumen_estadisticas_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    atletas = equipo.atletas.all()

    # Obtener solo los partidos en los que participó este equipo
    partidos_del_equipo = Partido.objects.filter(equipo_local=equipo)

    resumen_por_atleta = []

    for atleta in atletas:
        # Filtrar estadísticas solo de esos partidos
        stats = Estadistica.objects.filter(
            atleta=atleta,
            partido__in=partidos_del_equipo
        )

        totales = stats.aggregate(
            puntos=Sum('puntos'),
            saques=Sum('saques'),
            remates=Sum('remates'),
            bloqueos=Sum('bloqueos'),
            armadas=Sum('armadas'),
            recepciones=Sum('recepciones'),
            errores=Sum('errores')
        )

        resumen_por_atleta.append({
            'atleta': atleta,
            'totales': totales
        })

    return render(request, 'estadisticas/resumen_equipo.html', {
        'equipo': equipo,
        'resumen_por_atleta': resumen_por_atleta
    })

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def resumen_estadisticas_equipo_grafico(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    atletas = equipo.atletas.all()

    # Filtrar solo los partidos en los que jugó el equipo
    partidos_equipo = Partido.objects.filter(equipo_local=equipo)

    # Filtrar estadísticas solo de atletas de ese equipo y en esos partidos
    estadisticas = Estadistica.objects.filter(
        atleta__in=atletas,
        partido__in=partidos_equipo
    )

    if not estadisticas.exists():
        return render(request, 'estadisticas/resumen_equipo_grafico.html', {
            'equipo': equipo,
            'sin_datos': True
        })

    datos = estadisticas.aggregate(
        puntos=Sum('puntos') or 0,
        saques=Sum('saques') or 0,
        remates=Sum('remates') or 0,
        bloqueos=Sum('bloqueos') or 0,
        armadas=Sum('armadas') or 0,
        recepciones=Sum('recepciones') or 0,
        errores=Sum('errores') or 0,
    )

    def normalizar(valor, maximo=200):
        valor = valor or 0
        return min(round((valor / maximo) * 100), 1000000)

    radar_datos = {
        'Remates': datos['remates'],
        'Bloqueo': datos['bloqueos'],
        'Recepción': datos['recepciones'],
        'Armada': datos['armadas'],
        'Saques': datos['saques'],
    }

    radar_labels = list(radar_datos.keys())
    radar_values = [normalizar(valor) for valor in radar_datos.values()]

    puntos_neto = max(datos['puntos'] - datos['errores'], 0)
    acciones_totales = sum([
        datos['puntos'], datos['saques'],
        datos['remates'], datos['bloqueos'],
        datos['armadas'], datos['recepciones'],
        datos['errores'],
    ]) or 1

    aportes = datos['armadas'] + datos['recepciones']
    relacion_apoyo = round(min((aportes / acciones_totales) * 100, 100), 2)

    colores_caracteristicas = {
        'Remates': '#e74c3c',
        'Bloqueo': '#8e44ad',
        'Recepción': '#27ae60',
        'Armada': '#f39c12',
        'Saques': '#3498db',
    }

    mayor = max(radar_datos, key=radar_datos.get)
    menor = min(radar_datos, key=radar_datos.get)
    color_destacado = colores_caracteristicas.get(mayor, 'rgba(54, 162, 235, 0.6)')

    leyendas = {
        'Remates': "El equipo destaca en Remates, mostrando potencia ofensiva.",
        'Bloqueo': "Gran capacidad defensiva en Bloqueos, conteniendo ataques rivales.",
        'Recepción': "Recepciones consistentes que permiten fluidez en el juego.",
        'Armada': "Alta participación en Armadas, clave para organizar jugadas.",
        'Saques': "Buena efectividad en Saques para iniciar jugadas.",
    }

    leyenda_mayor = leyendas.get(mayor, "")
    leyenda_menor = (
        f"En cambio, <strong>{menor}</strong> es su punto más bajo, indicando un área de mejora."
    )

    context = {
        'equipo': equipo,
        'datos': datos,
        'puntos_neto': puntos_neto,
        'relacion_apoyo': relacion_apoyo,
        'aportes': aportes,
        'radar_labels': radar_labels,
        'radar_values': radar_values,
        'color_destacado': color_destacado,
        'leyenda_mayor': leyenda_mayor,
        'leyenda_menor': leyenda_menor,
    }

    return render(request, 'estadisticas/resumen_equipo_grafico.html', context)

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_pagos_view(request):
    año_actual = datetime.now().year
    año = int(request.GET.get('año', año_actual))
    categoria = request.GET.get('categoria')
    cedula = request.GET.get('cedula', '').strip()
    nombre = request.GET.get('nombre', '').strip()
    mes_inicio = int(request.GET.get('mes_inicio') or 1)
    mes_fin = int(request.GET.get('mes_fin') or 12)
    estado_filtro = request.GET.get('estado', '')

    atletas = Atleta.objects.all()

    if categoria:
        atletas = atletas.filter(categoria=categoria)
    if nombre:
        atletas = atletas.filter(nombre__icontains=nombre)

    atletas_filtrados_por_cedula = False
    if cedula:
        atletas = atletas.filter(cedula__icontains=cedula)
        if atletas.count() == 1:
            atletas_filtrados_por_cedula = True

    resumen = []
    for atleta in atletas:
        pagos = []
        total_pagado = 0
        total_pendiente = 0
        tiene_estado = False

        for mes in range(mes_inicio, mes_fin + 1):
            mensualidad = Mensualidad.objects.filter(atleta=atleta, año=año, mes=mes).first()
            if mensualidad:
                monto = float(mensualidad.monto_pagado)
                if mensualidad.exonerado:
                    estado = "exonerado"
                elif monto >= 5.00:
                    estado = "pagado"
                elif monto > 0:
                    estado = "parcial"
                else:
                    estado = "no_pagado"
            else:
                monto = 0.00
                estado = "no_pagado"

            pagos.append({'mes': mes, 'monto': monto, 'estado': estado})

            if estado != "exonerado":
                total_pagado += monto
                if monto < 5:
                    total_pendiente += (5 - monto)

            if estado == estado_filtro:
                tiene_estado = True

        if estado_filtro and not tiene_estado and not atletas_filtrados_por_cedula:
            continue

        resumen.append({
            'id': atleta.id,
            'nombre': atleta.nombre,
            'apellido': atleta.apellido,
            'cedula': atleta.cedula,
            'categoria': atleta.categoria,
            'pagos': pagos,
            'total_pagado': total_pagado,
            'total_pendiente': total_pendiente
        })

    paginator = Paginator(resumen, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    meses = [(i, calendar.month_name[i]) for i in range(mes_inicio, mes_fin + 1)]
    categorias = Atleta.objects.values_list('categoria', flat=True).distinct()

    context = {
        'resumen': page_obj,
        'categorias': categorias,
        'año_actual': año_actual,
        'año_seleccionado': año,
        'categoria_seleccionada': categoria,
        'cedula': cedula,
        'nombre': nombre,
        'mes_inicio': mes_inicio,
        'mes_fin': mes_fin,
        'estado': estado_filtro,
        'meses': meses,
        'page_obj': page_obj,
    }

    return render(request, 'reportes/reporte_pagos.html', context)

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def exportar_pagos_excel(request):
    from openpyxl.styles import Font, Alignment, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.drawing.image import Image as XLImage

    año = int(request.GET.get('año', date.today().year))
    categoria = request.GET.get('categoria')
    nombre = request.GET.get('nombre')
    cedula = request.GET.get('cedula')
    estado = request.GET.get('estado')  # pagado, pendiente, parcial, exonerado
    mes_inicio = int(request.GET.get('mes_inicio', 1))
    mes_fin = int(request.GET.get('mes_fin', 12))

    atletas = Atleta.objects.all()
    if categoria:
        atletas = atletas.filter(categoria=categoria)
    if nombre:
        atletas = atletas.filter(nombre__icontains=nombre)

    atletas_filtrados_por_cedula = False
    if cedula:
        atletas = atletas.filter(cedula__icontains=cedula)
        if atletas.count() == 1:
            atletas_filtrados_por_cedula = True


    data = []
    meses = [(i, date(1900, i, 1).strftime('%b')) for i in range(mes_inicio, mes_fin + 1)]

    for atleta in atletas:
        fila = {
            'Nombre': atleta.nombre,
            'Cédula': atleta.cedula,
            'Categoría': atleta.categoria,
        }
        total_pagado = 0
        total_pendiente = 0
        tiene_parcial = False
        tiene_exonerado = False
        todos_pagados = True

        for mes_num, mes_nombre in meses:
            mensualidad = Mensualidad.objects.filter(atleta=atleta, año=año, mes=mes_num).first()
            if mensualidad:
                monto = float(mensualidad.monto_pagado)
                if mensualidad.exonerado:
                    fila[mes_nombre] = "E"
                    tiene_exonerado = True
                elif monto >= 5:
                    fila[mes_nombre] = monto
                elif monto > 0:
                    fila[mes_nombre] = monto
                    tiene_parcial = True
                    todos_pagados = False
                else:
                    fila[mes_nombre] = 0
                    todos_pagados = False
                total_pagado += monto if not mensualidad.exonerado else 0
                total_pendiente += 0 if (monto >= 5 or mensualidad.exonerado) else (5 - monto)
            else:
                fila[mes_nombre] = 0
                total_pendiente += 5
                todos_pagados = False

        # Nueva lógica de filtro por estado (igual al PDF)
        tiene_estado = False

        for mes_num, _ in meses:
            mensualidad = Mensualidad.objects.filter(atleta=atleta, año=año, mes=mes_num).first()
            if mensualidad:
                monto = float(mensualidad.monto_pagado)
                if mensualidad.exonerado:
                    estado_mes = "exonerado"
                elif monto >= 5:
                    estado_mes = "pagado"
                elif monto > 0:
                    estado_mes = "parcial"
                else:
                    estado_mes = "no_pagado"
            else:
                estado_mes = "no_pagado"

            if estado and estado_mes == estado:
                tiene_estado = True

        if estado and not tiene_estado and not atletas_filtrados_por_cedula:
            continue

        fila['Pagado'] = total_pagado
        fila['Pendiente'] = total_pendiente
        data.append(fila)

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Pagos')

    output.seek(0)
    wb = load_workbook(output)
    ws = wb.active
    ws.insert_rows(1, amount=4)

    # Logo más grande
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'logo-olympo.jpeg')
    if os.path.exists(logo_path):
        img = XLImage(logo_path)
        img.width = 100
        img.height = 100
        ws.add_image(img, 'A1')

    # Título y subtítulo
    ws['C1'] = "Escuela Deportiva OLYMPO"
    ws['C2'] = f"Reporte de Pagos - Año {año}"
    ws['C1'].font = Font(size=14, bold=True)
    ws['C2'].font = Font(size=12, bold=True)
    ws['C1'].alignment = Alignment(vertical="center")
    ws['C2'].alignment = Alignment(vertical="center")
    ws.merge_cells('C1:H1')
    ws.merge_cells('C2:H2')
    ws.row_dimensions[1].height = 30
    ws.row_dimensions[2].height = 24

    # Encabezado de tabla
    header_fill = PatternFill(start_color="FFC000", end_color="FFC000", fill_type="solid")
    for col in range(1, ws.max_column + 1):
        cell = ws.cell(row=5, column=col)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.fill = header_fill

    # Ancho personalizado: Categoría más estrecho
    for col in range(1, ws.max_column + 1):
        col_letter = get_column_letter(col)
        header = ws[f'{col_letter}5'].value
        if header == 'Categoría':
            ws.column_dimensions[col_letter].width = 13
        else:
            ws.column_dimensions[col_letter].width = 13

    # Estilo para celdas especiales
    for row in ws.iter_rows(min_row=6, max_row=ws.max_row):
        for cell in row:
            if cell.value == "E":
                cell.font = Font(bold=True, color="0000FF")
                cell.alignment = Alignment(horizontal="center")
            elif isinstance(cell.value, (int, float)):
                cell.alignment = Alignment(horizontal="center")

    final_output = io.BytesIO()
    wb.save(final_output)
    final_output.seek(0)

    response = HttpResponse(
        final_output,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="reporte_pagos.xlsx"'
    return response

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def exportar_pagos_pdf(request):
    from datetime import datetime
    año = int(request.GET.get('año', date.today().year))
    categoria = request.GET.get('categoria')
    nombre = request.GET.get('nombre')
    cedula = request.GET.get('cedula')
    estado = request.GET.get('estado')  # 'pagado', 'pendiente', 'parcial', 'exonerado'
    mes_inicio = int(request.GET.get('mes_inicio', 1))
    mes_fin = int(request.GET.get('mes_fin', 12))

    atletas = Atleta.objects.all()
    if categoria:
        atletas = atletas.filter(categoria=categoria)
    if nombre:
        atletas = atletas.filter(nombre__icontains=nombre)
    if cedula:
        atletas = atletas.filter(cedula__icontains=cedula)

    atletas_filtrados_por_cedula = False
    if cedula and atletas.count() == 1:
        atletas_filtrados_por_cedula = True

    meses = [(i, date(1900, i, 1).strftime('%b')) for i in range(mes_inicio, mes_fin + 1)]
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=landscape(letter))
    width, height = landscape(letter)

    # Para numerar páginas
    page_number = 1

    headers = ["Nombre", "Cédula", "Categoría"] + [m[1][:3] for m in meses] + ["Pagado", "Pendiente"]
    # Ajuste dinámico: si hay 12 meses, reduce un poco las columnas
    if len(meses) == 12:
        col_width = max(42, min(55, (width - 80) // len(headers)))
    else:
        col_width = max(45, min(60, (width - 100) // len(headers)))


    def imprimir_encabezado(pagina_inicial=False):
        nonlocal y
        y = height - 40
        x = 40
        if pagina_inicial:
            # Logo solo en la primera página
            logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'logo-olympo.jpeg')
            if os.path.exists(logo_path):
                logo = ImageReader(logo_path)
                p.drawImage(logo, x, y - 40, width=80, height=80)

            # Título
            p.setFont("Helvetica-Bold", 16)
            p.drawString(x + 90, y, "Escuela Deportiva OLYMPO")
            p.setFont("Helvetica", 12)
            p.drawString(x + 90, y - 20, f"Reporte de Pagos - Año {año}")
            y -= 60
        else:
            y = height - 40
            p.setFont("Helvetica", 7)

        # Encabezado de tabla
        p.setFont("Helvetica-Bold", 8)
        for i, h in enumerate(headers):
            p.drawString(x + i * col_width, y, h)
        y -= 18
        p.setFont("Helvetica", 7)

    def imprimir_pie_pagina():
        fecha_export = datetime.now().strftime("%d/%m/%Y %H:%M")
        p.setFont("Helvetica", 8)
        p.drawRightString(width - 60, 25, f"Página {page_number}")
        p.drawString(40, 25, f"Exportado: {fecha_export}")
        p.setFont("Helvetica", 7)

    # Primera página con logo
    imprimir_encabezado(pagina_inicial=True)

    y = height - 40 - 60 - 18  # Ajusta y para la primera fila de datos

    for atleta in atletas:
        fila = [atleta.nombre, atleta.cedula, atleta.categoria]
        total_pagado = 0
        total_pendiente = 0
        pagos_mes = []
        tiene_estado = False

        for mes_num, _ in meses:
            mensualidad = Mensualidad.objects.filter(atleta=atleta, año=año, mes=mes_num).first()
            if mensualidad:
                monto = float(mensualidad.monto_pagado)
                if mensualidad.exonerado:
                    estado_mes = "exonerado"
                    pagos_mes.append("E")
                elif monto >= 5:
                    estado_mes = "pagado"
                    pagos_mes.append(f"{monto:.2f}")
                elif monto > 0:
                    estado_mes = "parcial"
                    pagos_mes.append(f"{monto:.2f}")
                else:
                    estado_mes = "no_pagado"
                    pagos_mes.append("—")
                if estado_mes == estado:
                    tiene_estado = True
                if estado_mes != "exonerado":
                    total_pagado += monto
                    if monto < 5:
                        total_pendiente += (5 - monto)
            else:
                pagos_mes.append("—")
                total_pendiente += 5
                if estado == "no_pagado":
                    tiene_estado = True

            # Si no hay ninguna mensualidad creada y estamos filtrando por pendiente,
            # igual debemos considerar que está pendiente.
            if not Mensualidad.objects.filter(atleta=atleta, año=año, mes__gte=mes_inicio, mes__lte=mes_fin).exists():
                if estado == "no_pagado":
                    tiene_estado = True

        if estado and not tiene_estado and not atletas_filtrados_por_cedula:
            continue

        fila.extend(pagos_mes)
        fila.append(f"{total_pagado:.2f}")
        fila.append(f"{total_pendiente:.2f}")

        for i, val in enumerate(fila):
            p.drawString(40 + i * col_width, y, str(val))
        y -= 14

        if y < 50:
            imprimir_pie_pagina()
            p.showPage()
            page_number += 1
            imprimir_encabezado(pagina_inicial=False)
            y -= 18  # Ajuste para la siguiente fila de datos

    # Pie de página en la última página
    imprimir_pie_pagina()

    p.save()
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename='reporte_pagos.pdf')

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_atletas_view(request):
    categorias = ['U9', 'U11', 'U13', 'U15', 'U17', 'U19', 'U21', 'U23', 'Libre']
    atletas = Atleta.objects.all()
    
    cedula = request.GET.get('cedula', '').strip()
    nombre = request.GET.get('nombre', '').strip()
    categoria = request.GET.get('categoria', '')
    edad_min = request.GET.get('edad_min')
    edad_max = request.GET.get('edad_max')
    sexo = request.GET.get('sexo', '').strip()

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

    años_disponibles = sorted({a.fecha_registro.year for a in Atleta.objects.all()})

    # PAGINACIÓN
    from django.core.paginator import Paginator
    paginator = Paginator(atletas, 15)  # 15 atletas por página
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        'atletas': page_obj,
        'años_disponibles': años_disponibles,
        'categorias': categorias,
        'filtros': {
            'cedula': cedula,
            'nombre': nombre,
            'categoria': categoria,
            'edad_min': edad_min,
            'edad_max': edad_max,
            'sexo': sexo,
        },
        'page_obj': page_obj,
    }
    return render(request, 'reportes/reporte_atletas.html', context)

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

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_atletas_excel(request):
    from openpyxl.styles import Font, Alignment, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl import load_workbook

    atletas = aplicar_filtros(request)
    
    data = []
    for a in atletas:
        data.append({
            'Nombre y Apellido': f"{a.nombre} {a.apellido}",
            'Cédula': a.cedula,
            'Categoría': a.categoria,
            'Edad': a.calcular_edad(),
            'Sexo': a.sexo,
            'Teléfono': a.telefono,
            'Dirección': a.direccion,
        })

    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Atletas')

    output.seek(0)
    wb = load_workbook(output)
    ws = wb.active
    ws.insert_rows(1, amount=4)

    # Logo y encabezados
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'logo-olympo.jpeg')
    if os.path.exists(logo_path):
        img = XLImage(logo_path)
        img.width = 100
        img.height = 100
        ws.add_image(img, 'A1')

    ws['C1'] = "Escuela Deportiva OLYMPO"
    ws['C2'] = "Reporte de Atletas"
    ws['C1'].font = Font(size=14, bold=True)
    ws['C2'].font = Font(size=12, bold=True)
    ws['C1'].alignment = Alignment(vertical="center")
    ws['C2'].alignment = Alignment(vertical="center")
    ws.merge_cells('C1:H1')
    ws.merge_cells('C2:H2')
    ws.row_dimensions[1].height = 30
    ws.row_dimensions[2].height = 24

    # Estilo encabezado tabla
    header_fill = PatternFill(start_color="FFC000", end_color="FFC000", fill_type="solid")
    for col in range(1, ws.max_column + 1):
        cell = ws.cell(row=5, column=col)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.fill = header_fill

    # Anchos personalizados y alineación por columna
    for col in range(1, ws.max_column + 1):
        col_letter = get_column_letter(col)
        header = ws[f'{col_letter}5'].value

        if header == 'Nombre y Apellido':
            ws.column_dimensions[col_letter].width = 30
            align = Alignment(horizontal="left")
        elif header == 'Cédula':
            ws.column_dimensions[col_letter].width = 16
            align = Alignment(horizontal="center")
        elif header == 'Categoría':
            ws.column_dimensions[col_letter].width = 14
            align = Alignment(horizontal="center")
        elif header == 'Edad':
            ws.column_dimensions[col_letter].width = 10
            align = Alignment(horizontal="center")
        elif header == 'Sexo':
            ws.column_dimensions[col_letter].width = 10
            align = Alignment(horizontal="center")
        elif header == 'Teléfono':
            ws.column_dimensions[col_letter].width = 18
            align = Alignment(horizontal="center")
        elif header == 'Dirección':
            ws.column_dimensions[col_letter].width = 35
            align = Alignment(horizontal="left")
        else:
            align = Alignment(horizontal="center")

        # Aplicar alineación a toda la columna
        for row in ws.iter_rows(min_row=6, max_row=ws.max_row, min_col=col, max_col=col):
            for cell in row:
                cell.alignment = align

    final_output = io.BytesIO()
    wb.save(final_output)
    final_output.seek(0)

    response = HttpResponse(
        final_output,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="reporte_atletas.xlsx"'
    return response

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_atletas_pdf(request):
    atletas = aplicar_filtros(request)
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    col_widths = [100, 60, 60, 60, 60, 80, 140]
    headers = ["Nombre y Apellido", "Cédula", "Categoría", "Edad", "Sexo", "Teléfono", "Dirección"]

    y = height - 40
    page_number = 1

    def encabezado(pagina_inicial=False):
        nonlocal y
        y = height - 40
        x = 40

        if pagina_inicial:
            # Logo
            logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'logo-olympo.jpeg')
            if os.path.exists(logo_path):
                logo = ImageReader(logo_path)
                p.drawImage(logo, x, y - 40, width=80, height=80)

            # Título
            p.setFont("Helvetica-Bold", 16)
            p.drawString(x + 90, y, "Escuela Deportiva OLYMPO")
            p.setFont("Helvetica", 12)
            p.drawString(x + 90, y - 20, "Reporte de Atletas")
            y -= 60
        else:
            y = height - 40

        # Encabezado de tabla
        p.setFont("Helvetica-Bold", 8)
        curr_x = x
        for i, header in enumerate(headers):
            p.drawString(curr_x, y, header)
            curr_x += col_widths[i]
        y -= 18
        p.setFont("Helvetica", 7)

    def pie_pagina():
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
        p.setFont("Helvetica", 8)
        p.drawRightString(width - 40, 25, f"Página {page_number}")
        p.drawString(40, 25, f"Exportado: {fecha}")

    # Primer encabezado
    encabezado(pagina_inicial=True)

    # Datos
    for atleta in atletas:
        fila = [
            f"{atleta.nombre} {atleta.apellido}",
            atleta.cedula,
            atleta.categoria,
            atleta.calcular_edad(),
            atleta.sexo,
            atleta.telefono,
            atleta.direccion,

        ]

        curr_x = 40
        for i, dato in enumerate(fila):
            p.drawString(curr_x, y, str(dato))
            curr_x += col_widths[i]
        y -= 14

        if y < 50:
            pie_pagina()
            p.showPage()
            page_number += 1
            encabezado(pagina_inicial=False)
            y -= 18

    pie_pagina()
    p.save()
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename='reporte_atletas.pdf')


def parse_fecha(fecha_str):
    if not fecha_str:  # ✅ Maneja None y cadenas vacías
        return None
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(fecha_str, fmt).date()
        except ValueError:
            continue
    return None

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_estadisticas(request):
    cedula = request.GET.get('cedula', '')
    fecha_inicio = request.GET.get('fecha_inicio', '')
    fecha_fin = request.GET.get('fecha_fin', '')

    fecha_inicio_obj = parse_fecha(fecha_inicio)
    fecha_fin_obj = parse_fecha(fecha_fin)

    estadisticas = Estadistica.objects.select_related('atleta')

    if fecha_inicio_obj:
        estadisticas = estadisticas.filter(partido__fecha__gte=fecha_inicio_obj)
    if fecha_fin_obj:
        estadisticas = estadisticas.filter(partido__fecha__lte=fecha_fin_obj)
    if cedula:
        estadisticas = estadisticas.filter(atleta__cedula__icontains=cedula)

    # Agrupar y sumar estadísticas por atleta
    atletas_dict = defaultdict(lambda: {
        'puntos': 0,
        'saques': 0,
        'remates': 0,
        'bloqueos': 0,
        'recepciones': 0,
        'armadas': 0,
        'errores': 0,
        'atleta': None
    })

    for est in estadisticas:
        data = atletas_dict[est.atleta.id]
        data['atleta'] = est.atleta
        data['puntos'] += est.puntos or 0
        data['saques'] += est.saques or 0
        data['remates'] += est.remates or 0
        data['bloqueos'] += est.bloqueos or 0
        data['recepciones'] += est.recepciones or 0
        data['armadas'] += est.armadas or 0
        data['errores'] += est.errores or 0

    atletas_data = list(atletas_dict.values())

    paginator = Paginator(atletas_data, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'cedula': cedula,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
    }
    return render(request, 'reportes/reporte_estadisticas.html', context)

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def exportar_estadisticas_pdf(request, atleta_id):
    atleta = get_object_or_404(Atleta, id=atleta_id)
    estadisticas = Estadistica.objects.filter(atleta=atleta).select_related('partido')

    # ✅ Filtro por fechas
    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    fecha_inicio_obj = parse_fecha(fecha_inicio)
    fecha_fin_obj = parse_fecha(fecha_fin)

    if fecha_inicio_obj:
        estadisticas = estadisticas.filter(partido__fecha__gte=fecha_inicio_obj)
    if fecha_fin_obj:
        estadisticas = estadisticas.filter(partido__fecha__lte=fecha_fin_obj)

    estadisticas = estadisticas.order_by('-partido__fecha')

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    page_number = 1

    # 🎨 Colores y estilos
    COLOR_PRIMARIO = colors.HexColor("#2C3E50")
    COLOR_SECUNDARIO = colors.HexColor("#2980B9")
    COLOR_TEXTO = colors.HexColor("#000000")

    def encabezado(pagina_inicial=False):
        # Logo y título
        if pagina_inicial:
            logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'logo-olympo.jpeg')
            if os.path.exists(logo_path):
                p.drawImage(logo_path, 40, height - 90, width=70, height=70, preserveAspectRatio=True)
            p.setFont("Helvetica-Bold", 18)
            p.setFillColor(COLOR_PRIMARIO)
            p.drawString(120, height - 60, "Escuela Deportiva OLYMPO")
            p.setFont("Helvetica", 12)
            p.setFillColor(COLOR_TEXTO)
            p.drawString(120, height - 80, "Reporte de Estadísticas Individuales")
            # Línea divisoria debajo del logo y título
            p.setStrokeColor(COLOR_PRIMARIO)
            p.setLineWidth(1)
            p.line(40, height - 100, width - 40, height - 100)
        else:
            p.setFont("Helvetica-Bold", 12)
            p.setFillColor(COLOR_PRIMARIO)
            p.drawString(40, height - 65, "Reporte de Estadísticas")
            p.setStrokeColor(COLOR_PRIMARIO)
            p.setLineWidth(1)
            p.line(40, height - 75, width - 40, height - 75)
        p.setFillColor(COLOR_TEXTO)

    def pie_pagina():
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
        p.setFont("Helvetica", 8)
        p.setFillColor(COLOR_TEXTO)
        p.drawRightString(width - 40, 25, f"Página {page_number}")
        p.drawString(40, 25, f"Exportado: {fecha}")

    # 📝 Página inicial
    encabezado(True)
    y_inicio = height - 120

    if estadisticas.exists():
        # 📊 Cálculos
        total_puntos = sum(e.puntos or 0 for e in estadisticas)
        errores = sum(e.errores or 0 for e in estadisticas)
        remates = sum(e.remates or 0 for e in estadisticas)
        bloqueos = sum(e.bloqueos or 0 for e in estadisticas)
        recepciones = sum(e.recepciones or 0 for e in estadisticas)
        armadas = sum(e.armadas or 0 for e in estadisticas)
        saques = sum(e.saques or 0 for e in estadisticas)

        puntos_netos = max(total_puntos - errores, 0)
        aportes = armadas + recepciones
        acciones = sum([total_puntos, saques, remates, bloqueos, armadas, recepciones, errores]) or 1
        relacion_apoyo = round(min((aportes / acciones) * 100, 100), 2)

        componentes = {
            'Remates': remates,
            'Bloqueos': bloqueos,
            'Recepciones': recepciones,
            'Armadas': armadas,
            'Saques': saques,
        }
        punto_fuerte = max(componentes, key=componentes.get)
        punto_debil = min(componentes, key=componentes.get)

        resumen = [
            ("Total de puntos", total_puntos),
            ("Errores cometidos", errores),
            ("Puntos netos", puntos_netos),
            ("Aportes (Armadas + Recepciones)", aportes),
            ("Relación Apoyo/Acción (%)", f"{relacion_apoyo:.2f}%"),
            ("Punto fuerte", f"{punto_fuerte} ✅"),
            ("Punto débil", f"{punto_debil} ⚠️"),
        ]

        # Información en dos columnas
        p.setFont("Helvetica-Bold", 12)
        p.setFillColor(COLOR_PRIMARIO)
        p.drawString(40, y_inicio, "Información del Atleta")
        p.setFillColor(COLOR_TEXTO)
        p.setFont("Helvetica", 10)
        y_info = y_inicio - 20
        x_left = 40
        x_right = 220

        # Columna izquierda
        p.drawString(x_left, y_info, f"Nombre: {atleta.nombre} {atleta.apellido}")
        p.drawString(x_left, y_info - 15, f"Categoría: {atleta.categoria}")

        # Columna derecha
        p.drawString(x_right, y_info, f"Cédula: {atleta.cedula}")
        p.drawString(x_right, y_info - 15, f"Posición: {atleta.posicion}")

        # Rango de fechas (debajo de ambas columnas si aplica)
        y_rango = y_info - 35
        if fecha_inicio and fecha_fin:
            p.drawString(x_left, y_rango, f"Rango de fechas: {fecha_inicio} a {fecha_fin}")

        # Resumen de estadísticas en una sola columna abajo
        y_stats = y_rango - 30
        p.setFont("Helvetica-Bold", 12)
        p.setFillColor(COLOR_PRIMARIO)
        p.drawString(40, y_stats, "Resumen de Estadísticas:")
        p.setFillColor(COLOR_TEXTO)
        p.setFont("Helvetica", 10)
        y_stats -= 20
        for label, value in resumen:
            p.drawString(60, y_stats, f"{label}: {value}")
            y_stats -= 15

        # Línea divisoria debajo de los bloques
        p.setStrokeColor(COLOR_SECUNDARIO)
        p.setLineWidth(0.5)
        p.line(40, y_stats - 10, width - 40, y_stats - 10)

        # 📈 Gráfico de barras debajo
        fig1, ax1 = plt.subplots()
        labels = ['Puntos', 'Saques', 'Remates', 'Bloqueos', 'Errores']
        values = [total_puntos, saques, remates, bloqueos, errores]
        ax1.bar(labels, values, color=['#3498db', '#1abc9c', '#e67e22', '#9b59b6', '#e74c3c'])
        ax1.set_title(
            f"DESEMPEÑO GENERAL - {atleta.nombre}",
            fontsize=14, fontweight='bold', color="#2C3E50"
        )
        ax1.set_ylabel("Cantidad")
        plt.xticks(rotation=45)
        plt.tight_layout()
        chart_buffer1 = BytesIO()
        plt.savefig(chart_buffer1, format='png')
        plt.close(fig1)
        chart_buffer1.seek(0)
        p.drawImage(ImageReader(chart_buffer1), 40, y_stats - 250, width=5.5 * inch, height=3.2 * inch)

    else:
        p.setFont("Helvetica-Oblique", 11)
        p.drawString(40, height - 150, "Este atleta no tiene estadísticas registradas.")

    # Guardar página inicial
    pie_pagina()
    p.showPage()
    page_number += 1

    # 📄 Página radar y tabla
    encabezado(False)

    if estadisticas.exists():
        # Radar (sin números internos)
        fig2 = plt.figure()
        categories = list(componentes.keys())
        values = list(componentes.values())
        N = len(categories)
        angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
        values += values[:1]
        angles += angles[:1]
        ax2 = plt.subplot(111, polar=True)
        ax2.plot(angles, values, color="#DF1212", linewidth=2)
        ax2.fill(angles, values, color="#DF1212", alpha=0.25)
        ax2.set_xticks(angles[:-1])
        ax2.set_xticklabels(categories)
        ax2.set_yticklabels([])  # Elimina los números internos
        # Mejorar el título para que no se corte
        titulo_radar = f"Habilidades Técnicas - {atleta.nombre}"
        ax2.set_title(titulo_radar, fontsize=14, fontweight='bold', color="#2C3E50", y=1.1)

        plt.tight_layout()
        radar_buffer = BytesIO()
        plt.savefig(radar_buffer, format='png')
        plt.close(fig2)
        radar_buffer.seek(0)
        p.drawImage(ImageReader(radar_buffer), 50, height - 400, width=5.5 * inch, height=3.5 * inch)

        # Tabla de partidos
        y_tabla = height - 420
        p.setFont("Helvetica-Bold", 12)
        p.setFillColor(COLOR_PRIMARIO)
        p.drawString(40, y_tabla, "Estadísticas por partido")
        p.setFillColor(COLOR_TEXTO)
        y_tabla -= 20

        columnas = ["Fecha", "Rival", "Puntos", "Saques", "Remates", "Bloqueos", "Recepciones", "Armadas", "Errores"]
        x_pos = [40, 100, 190, 250, 300, 360, 430, 500, 560]

        def dibujar_encabezados_tabla(y_pos):
            """Dibuja los encabezados de la tabla en la posición dada"""
            p.setFont("Helvetica-Bold", 9)
            p.setFillColor(COLOR_PRIMARIO)
            for i, col in enumerate(columnas):
                p.drawString(x_pos[i], y_pos, col)
            p.setFillColor(COLOR_TEXTO)
            p.setFont("Helvetica", 8)
            return y_pos - 15

        # 👉 Dibujar encabezados iniciales
        y_tabla = dibujar_encabezados_tabla(y_tabla)

        # 👉 Filas de la tabla
        for e in estadisticas:
            datos = [
                e.partido.fecha.strftime("%d/%m/%Y"),
                e.partido.equipo_externo,
                e.puntos or 0,
                e.saques or 0,
                e.remates or 0,
                e.bloqueos or 0,
                e.recepciones or 0,
                e.armadas or 0,
                e.errores or 0
            ]
            for i, dato in enumerate(datos):
                p.drawString(x_pos[i], y_tabla, str(dato))

            y_tabla -= 12

            # 👉 Salto de página si no hay espacio
            if y_tabla < 50:
                pie_pagina()
                p.showPage()
                page_number += 1
                encabezado(False)
                y_tabla = height - 100  # 🔹 Ajuste para que no monte sobre la línea
                y_tabla = dibujar_encabezados_tabla(y_tabla)


    pie_pagina()
    p.save()
    buffer.seek(0)

    return FileResponse(buffer, as_attachment=False, filename=f'estadisticas_{atleta.nombre}.pdf')

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_estadisticas_equipo(request):
    equipo_param = request.GET.get('equipo', '').strip()        # puede ser id o nombre
    sexo_param = request.GET.get('sexo', '').strip()
    entrenador_text = request.GET.get('entrenador', '').strip() # fallback si dejas input de texto
    entrenador_id = request.GET.get('entrenador_id', '').strip()# nuevo select
    fecha_inicio = request.GET.get('fecha_inicio', '').strip()
    fecha_fin = request.GET.get('fecha_fin', '').strip()

    fecha_inicio_obj = parse_fecha(fecha_inicio)
    fecha_fin_obj = parse_fecha(fecha_fin)

    equipos = Equipo.objects.all()

    # equipo: si es dígito -> id; si no -> por nombre (no rompe tu lógica actual)
    if equipo_param:
        if equipo_param.isdigit():
            equipos = equipos.filter(id=int(equipo_param))
        else:
            equipos = equipos.filter(nombre__icontains=equipo_param)

    # sexo: normalizar valores ('M'/'F' o 'masculino'/'femenino'/'mixto')
    sexo_normalizado = ''
    if sexo_param:
        s = sexo_param.lower()
        if s in ('masculino', 'femenino', 'mixto'):
            sexo_normalizado = s
        elif s == 'm':
            sexo_normalizado = 'masculino'
        elif s == 'f':
            sexo_normalizado = 'femenino'
    if sexo_normalizado:
        equipos = equipos.filter(sexo_equipo=sexo_normalizado)

    # entrenador: por id (select) o por texto (nombre/apellido)
    if entrenador_id and entrenador_id.isdigit():
        equipos = equipos.filter(entrenador__id=int(entrenador_id))
    elif entrenador_text:
        equipos = equipos.filter(
            Q(entrenador__nombre__icontains=entrenador_text) |
            Q(entrenador__apellido__icontains=entrenador_text)
        )

    equipos_con_estadisticas = []
    for equipo in equipos:
        atletas = equipo.atletas.all()
        partidos_del_equipo = Partido.objects.filter(equipo_local=equipo)

        if fecha_inicio_obj:
            partidos_del_equipo = partidos_del_equipo.filter(fecha__gte=fecha_inicio_obj)
        if fecha_fin_obj:
            partidos_del_equipo = partidos_del_equipo.filter(fecha__lte=fecha_fin_obj)

        estadisticas = Estadistica.objects.filter(
            atleta__in=atletas,
            partido__in=partidos_del_equipo  # dejo tu campo tal cual para no romper
        )

        totales = estadisticas.aggregate(
            puntos=Sum('puntos'),
            saques=Sum('saques'),
            remates=Sum('remates'),
            bloqueos=Sum('bloqueos'),
            armadas=Sum('armadas'),
            recepciones=Sum('recepciones'),
            errores=Sum('errores'),
        )

        if estadisticas.exists():
            equipos_con_estadisticas.append({
                'equipo': equipo,
                'totales': {k: (v or 0) for k, v in totales.items()},
            })

    paginator = Paginator(equipos_con_estadisticas, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        'page_obj': page_obj,
        'todos_equipos': Equipo.objects.all(),
        'entrenadores': Entrenador.objects.all().order_by('nombre', 'apellido'),
        'equipo': equipo_param,
        'sexo': sexo_normalizado or sexo_param,  # mantiene selección en el form
        'entrenador': entrenador_text,
        'entrenador_id': entrenador_id,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
    }
    return render(request, 'reportes/reporte_estadisticas_equipo.html', context)

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def exportar_estadisticas_equipo_pdf(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    atletas = equipo.atletas.all()

    # Filtros de fecha
    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    fecha_inicio_obj = parse_fecha(fecha_inicio)
    fecha_fin_obj = parse_fecha(fecha_fin)

    partidos_del_equipo = Partido.objects.filter(equipo_local=equipo)
    if fecha_inicio_obj:
        partidos_del_equipo = partidos_del_equipo.filter(fecha__gte=fecha_inicio_obj)
    if fecha_fin_obj:
        partidos_del_equipo = partidos_del_equipo.filter(fecha__lte=fecha_fin_obj)
    partidos_del_equipo = partidos_del_equipo.order_by('-fecha')

    # Estadísticas acumuladas del equipo en esos partidos
    estadisticas = Estadistica.objects.filter(
        atleta__in=atletas,
        partido__in=partidos_del_equipo
    )

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    page_number = 1

    # 🎨 Estilo
    COLOR_PRIMARIO = colors.HexColor("#2C3E50")
    COLOR_SECUNDARIO = colors.HexColor("#2980B9")
    COLOR_TEXTO = colors.HexColor("#000000")

    def encabezado(pagina_inicial=False):
        if pagina_inicial:
            logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'logo-olympo.jpeg')
            if os.path.exists(logo_path):
                p.drawImage(logo_path, 40, height - 90, width=70, height=70, preserveAspectRatio=True)
            p.setFont("Helvetica-Bold", 18)
            p.setFillColor(COLOR_PRIMARIO)
            p.drawString(120, height - 60, "Escuela Deportiva OLYMPO")
            p.setFont("Helvetica", 12)
            p.setFillColor(COLOR_TEXTO)
            p.drawString(120, height - 80, "Reporte de Estadísticas por Equipo")
            p.setStrokeColor(COLOR_PRIMARIO)
            p.setLineWidth(1)
            p.line(40, height - 100, width - 40, height - 100)
        else:
            p.setFont("Helvetica-Bold", 12)
            p.setFillColor(COLOR_PRIMARIO)
            p.drawString(40, height - 65, "Reporte de Estadísticas")
            p.setStrokeColor(COLOR_PRIMARIO)
            p.setLineWidth(1)
            p.line(40, height - 75, width - 40, height - 75)
        p.setFillColor(COLOR_TEXTO)

    def pie_pagina():
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
        p.setFont("Helvetica", 8)
        p.setFillColor(COLOR_TEXTO)
        p.drawRightString(width - 40, 25, f"Página {page_number}")
        p.drawString(40, 25, f"Exportado: {fecha}")

    # 📝 Página 1
    encabezado(True)
    y_inicio = height - 120

    if estadisticas.exists():
        # Totales del equipo
        tot = estadisticas.aggregate(
            puntos=Sum('puntos'),
            saques=Sum('saques'),
            remates=Sum('remates'),
            bloqueos=Sum('bloqueos'),
            recepciones=Sum('recepciones'),
            armadas=Sum('armadas'),
            errores=Sum('errores'),
        )
        for k in list(tot.keys()):
            tot[k] = tot[k] or 0

        puntos_netos = max(tot['puntos'] - tot['errores'], 0)
        aportes = (tot['armadas'] or 0) + (tot['recepciones'] or 0)
        acciones = sum([
            tot['puntos'], tot['saques'], tot['remates'], tot['bloqueos'],
            tot['armadas'], tot['recepciones'], tot['errores']
        ]) or 1
        relacion_apoyo = round(min((aportes / acciones) * 100, 100), 2)

        componentes = {
            'Remates': tot['remates'],
            'Bloqueos': tot['bloqueos'],
            'Recepciones': tot['recepciones'],
            'Armadas': tot['armadas'],
            'Saques': tot['saques'],
        }
        punto_fuerte = max(componentes, key=componentes.get)
        punto_debil = min(componentes, key=componentes.get)

        resumen = [
            ("Total de puntos", tot['puntos']),
            ("Errores cometidos", tot['errores']),
            ("Puntos netos", puntos_netos),
            ("Aportes (Armadas + Recepciones)", aportes),
            ("Relación Apoyo/Acción (%)", f"{relacion_apoyo:.2f}%"),
            ("Punto fuerte", f"{punto_fuerte} ✅"),
            ("Punto débil", f"{punto_debil} ⚠️"),
        ]

        # 📌 Información del Equipo
        p.setFont("Helvetica-Bold", 12)
        p.setFillColor(COLOR_PRIMARIO)
        p.drawString(40, y_inicio, "Información del Equipo")
        p.setFillColor(COLOR_TEXTO)
        p.setFont("Helvetica", 10)

        x_left, x_right = 40, 260
        y_info = y_inicio - 20

        # Campos del equipo (defensivos por si alguno no existe)
        nombre_equipo = getattr(equipo, "nombre", str(equipo))
        sexo_equipo = getattr(equipo, "sexo_equipo", None)
        if hasattr(equipo, "get_sexo_equipo_display"):
            sexo_equipo = equipo.get_sexo_equipo_display()
        entrenador = getattr(equipo, "entrenador", None)
        entrenador_txt = str(entrenador) if entrenador else "—"
        cant_atletas = atletas.count()

        # Columna izquierda
        p.drawString(x_left, y_info, f"Nombre: {nombre_equipo}")
        p.drawString(x_left, y_info - 15, f"Sexo: {sexo_equipo or '—'}")

        # Columna derecha
        p.drawString(x_right, y_info, f"Entrenador: {entrenador_txt}")
        p.drawString(x_right, y_info - 15, f"Cantidad de atletas: {cant_atletas}")

        # Rango de fechas
        y_rango = y_info - 35
        if fecha_inicio and fecha_fin:
            p.drawString(x_left, y_rango, f"Rango de fechas: {fecha_inicio} a {fecha_fin}")

        # Resumen
        y_stats = y_rango - 30
        p.setFont("Helvetica-Bold", 12)
        p.setFillColor(COLOR_PRIMARIO)
        p.drawString(40, y_stats, "Resumen de Estadísticas:")
        p.setFillColor(COLOR_TEXTO)
        p.setFont("Helvetica", 10)
        y_stats -= 20
        for label, value in resumen:
            p.drawString(60, y_stats, f"{label}: {value}")
            y_stats -= 15

        # Línea
        p.setStrokeColor(COLOR_SECUNDARIO)
        p.setLineWidth(0.5)
        p.line(40, y_stats - 10, width - 40, y_stats - 10)

        # 📈 Barras
        fig1, ax1 = plt.subplots()
        labels = ['Puntos', 'Saques', 'Remates', 'Bloqueos', 'Errores']
        values = [tot['puntos'], tot['saques'], tot['remates'], tot['bloqueos'], tot['errores']]
        ax1.bar(labels, values, color=['#3498db', '#1abc9c', '#e67e22', '#9b59b6', '#e74c3c'])
        ax1.set_title(f"DESEMPEÑO GENERAL - {nombre_equipo}", fontsize=14, fontweight='bold', color="#2C3E50")
        ax1.set_ylabel("Cantidad")
        plt.xticks(rotation=45)
        plt.tight_layout()
        chart_buffer1 = BytesIO()
        plt.savefig(chart_buffer1, format='png')
        plt.close(fig1)
        chart_buffer1.seek(0)
        p.drawImage(ImageReader(chart_buffer1), 40, y_stats - 250, width=5.5 * inch, height=3.2 * inch)

    else:
        p.setFont("Helvetica-Oblique", 11)
        p.drawString(40, height - 150, "Este equipo no tiene estadísticas registradas en el rango seleccionado.")

    # Guardar página 1
    pie_pagina()
    p.showPage()
    page_number += 1

    # 📄 Página 2: Radar + Tabla por partido
    encabezado(False)

    if estadisticas.exists():
        # ---- Radar (sin números internos) ----
        fig2 = plt.figure()
        categories = list(componentes.keys())
        values = list(componentes.values())
        N = len(categories)
        angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
        values += values[:1]
        angles += angles[:1]
        ax2 = plt.subplot(111, polar=True)
        ax2.plot(angles, values, color="#DF1212", linewidth=2)
        ax2.fill(angles, values, color="#DF1212", alpha=0.25)
        ax2.set_xticks(angles[:-1])
        ax2.set_xticklabels(categories)
        ax2.set_yticklabels([])  # sin números internos
        ax2.set_title(f"Habilidades Técnicas - {nombre_equipo}", fontsize=14, fontweight='bold', color="#2C3E50", y=1.08)

        plt.tight_layout()
        radar_buffer = BytesIO()
        plt.savefig(radar_buffer, format='png')
        plt.close(fig2)
        radar_buffer.seek(0)
        p.drawImage(ImageReader(radar_buffer), 50, height - 400, width=5.5 * inch, height=3.5 * inch)

        # ---- Tabla por partido (agregado del equipo en cada partido) ----
        y_tabla = height - 420
        p.setFont("Helvetica-Bold", 12)
        p.setFillColor(COLOR_PRIMARIO)
        p.drawString(40, y_tabla, "Estadísticas por partido")
        p.setFillColor(COLOR_TEXTO)
        y_tabla -= 20

        columnas = ["Fecha", "Rival", "Puntos", "Saques", "Remates", "Bloqueos", "Recepciones", "Armadas", "Errores"]
        x_pos = [40, 100, 190, 250, 300, 360, 430, 500, 560]

        def dibujar_encabezados_tabla(y_pos):
            p.setFont("Helvetica-Bold", 9)
            p.setFillColor(COLOR_PRIMARIO)
            for i, col in enumerate(columnas):
                p.drawString(x_pos[i], y_pos, col)
            p.setFillColor(COLOR_TEXTO)
            p.setFont("Helvetica", 8)
            return y_pos - 15

        y_tabla = dibujar_encabezados_tabla(y_tabla)

        for partido in partidos_del_equipo:
            stats_p = Estadistica.objects.filter(atleta__in=atletas, partido=partido).aggregate(
                puntos=Sum('puntos'),
                saques=Sum('saques'),
                remates=Sum('remates'),
                bloqueos=Sum('bloqueos'),
                recepciones=Sum('recepciones'),
                armadas=Sum('armadas'),
                errores=Sum('errores'),
            )
            for k in list(stats_p.keys()):
                stats_p[k] = stats_p[k] or 0

            datos = [
                partido.fecha.strftime("%d/%m/%Y"),
                getattr(partido, "equipo_externo", "") or "—",
                stats_p['puntos'],
                stats_p['saques'],
                stats_p['remates'],
                stats_p['bloqueos'],
                stats_p['recepciones'],
                stats_p['armadas'],
                stats_p['errores'],
            ]

            for i, dato in enumerate(datos):
                p.drawString(x_pos[i], y_tabla, str(dato))
            y_tabla -= 12

            if y_tabla < 50:
                pie_pagina()
                p.showPage()
                page_number += 1
                encabezado(False)
                y_tabla = height - 100
                y_tabla = dibujar_encabezados_tabla(y_tabla)

    pie_pagina()
    p.save()
    buffer.seek(0)

    nombre_equipo = getattr(equipo, "nombre", str(equipo))
    return FileResponse(buffer, as_attachment=False, filename=f'estadisticas_equipo_{nombre_equipo}.pdf')

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_equipos(request):
    nombre = request.GET.get("nombre", "").strip()
    sexo_param = request.GET.get("sexo", "").strip()
    entrenador_id = request.GET.get("entrenador_id", "").strip()

    equipos = Equipo.objects.all().annotate(num_atletas=Count("atletas"))

    # filtro por nombre
    if nombre:
        equipos = equipos.filter(nombre__icontains=nombre)

    # filtro por sexo
    sexo_normalizado = ""
    if sexo_param:
        s = sexo_param.lower()
        if s in ("masculino", "femenino", "mixto"):
            sexo_normalizado = s
        elif s == "m":
            sexo_normalizado = "masculino"
        elif s == "f":
            sexo_normalizado = "femenino"
    if sexo_normalizado:
        equipos = equipos.filter(sexo_equipo=sexo_normalizado)

    # filtro por entrenador
    if entrenador_id and entrenador_id.isdigit():
        equipos = equipos.filter(entrenador__id=int(entrenador_id))

    paginator = Paginator(equipos, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "page_obj": page_obj,
        "entrenadores": Entrenador.objects.all().order_by("nombre", "apellido"),
        "nombre": nombre,
        "sexo": sexo_normalizado or sexo_param,
        "entrenador_id": entrenador_id,
    }
    return render(request, "reportes/reporte_equipos.html", context)

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def exportar_equipo_pdf(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    atletas = equipo.atletas.all()

    # response
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="equipo_{equipo.nombre}.pdf"'

    # estilos
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TituloPrincipal", fontSize=20, leading=24, alignment=1,
                              textColor=colors.HexColor("#2C3E50"), spaceAfter=16))
    styles.add(ParagraphStyle(name="SubTitulo", fontSize=14, leading=18,
                              textColor=colors.HexColor("#2980B9"), spaceAfter=10))
    styles.add(ParagraphStyle(name="NormalCustom", fontSize=11, leading=13, spaceAfter=4))

    # ruta logo
    logo_path = os.path.join(settings.BASE_DIR, "static", "img", "logo-olympo.jpeg")

    # encabezado / pie página
    def header_footer(canvas, doc):
        width, height = letter
        canvas.setStrokeColor(colors.HexColor("#2C3E50"))
        canvas.setLineWidth(1)
        canvas.line(40, height - 70, width - 40, height - 70)

        # logo
        if os.path.exists(logo_path):
            canvas.drawImage(logo_path, 40, height - 65, width=70, height=70, preserveAspectRatio=True)

        # título encabezado
        canvas.setFont("Helvetica-Bold", 14)
        canvas.setFillColor(colors.HexColor("#2C3E50"))
        canvas.drawString(120, height - 40, "Escuela Deportiva OLYMPO")

        # pie página
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.black)
        canvas.drawString(40, 30, f"Exportado: {fecha}")
        canvas.drawRightString(width - 40, 30, f"Página {doc.page}")

    # documento
    doc = SimpleDocTemplate(response, pagesize=letter,
                            rightMargin=40, leftMargin=40,
                            topMargin=90, bottomMargin=40)

    elements = []

    # título principal
    elements.append(Paragraph("Reporte del Equipo", styles["TituloPrincipal"]))
    elements.append(Spacer(1, 12))

    # encabezado de la sección de información del equipo
    elements.append(Paragraph("Información del Equipo", styles["SubTitulo"]))
    elements.append(Spacer(1, 4))

    # info del equipo (párrafos pegados a la izquierda)
    entrenador_txt = f"{equipo.entrenador.nombre} {equipo.entrenador.apellido}" if equipo.entrenador else "—"
    elements.append(Paragraph(f"<b>Nombre:</b> {equipo.nombre}", styles["NormalCustom"]))
    elements.append(Paragraph(f"<b>Categoría:</b> {equipo.categoria}", styles["NormalCustom"]))
    elements.append(Paragraph(f"<b>Entrenador:</b> {entrenador_txt}", styles["NormalCustom"]))
    elements.append(Paragraph(f"<b>Sexo:</b> {equipo.get_sexo_equipo_display()}", styles["NormalCustom"]))
    elements.append(Paragraph(f"<b>Cantidad de Atletas:</b> {equipo.atletas.count()}", styles["NormalCustom"]))
    elements.append(Spacer(1, 20))

    # tabla atletas
    if atletas.exists():
        elements.append(Paragraph("Listado de Atletas", styles["SubTitulo"]))
        data = [["Nombre", "Cédula", "Edad", "Teléfono", "Sexo"]]
        for a in atletas:
            data.append([
                f"{a.nombre} {a.apellido}",
                a.cedula,
                f"{a.calcular_edad()} años",
                a.telefono,
                a.sexo.title()
            ])
        # 👇 aumentamos la última columna (Sexo) de 50 → 70
        table = Table(data, hAlign="CENTER", colWidths=[140, 90, 60, 100, 70])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("Este equipo no tiene atletas asignados.", styles["NormalCustom"]))

    # construir pdf
    doc.build(elements, onFirstPage=header_footer, onLaterPages=header_footer)
    return response


# VISTA PRINCIPAL DEL REPORTE DE ENTRENADORES
@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_entrenadores_view(request):
    entrenadores = Entrenador.objects.all()

    # PAGINACIÓN
    paginator = Paginator(entrenadores, 10)  # 10 entrenadores por página
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "entrenadores": page_obj,
        "page_obj": page_obj,
    }
    return render(request, "reportes/reporte_entrenadores.html", context)


# EXPORTACIÓN EXCEL
@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_entrenadores_excel(request):
    data = []
    for e in Entrenador.objects.prefetch_related("equipo_set").all():
        # Calcular edad correctamente
        edad = ""
        if hasattr(e, "calcular_edad") and callable(e.calcular_edad):
            edad = e.calcular_edad()
        elif hasattr(e, "edad"):
            edad = e.edad

        # Equipos dirigidos (solo nombre)
        equipos_list = [eq.nombre for eq in e.equipo_set.all() if getattr(eq, "nombre", "")]
        equipos_txt = ", ".join(equipos_list) if equipos_list else "—"

        data.append({
            "Nombre y Apellido": f"{e.nombre} {e.apellido}",
            "Cédula": e.cedula,
            "Edad": edad,
            "Teléfono": e.telefono or "—",
            "Equipos Dirigidos": equipos_txt,
        })

    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Entrenadores")

    output.seek(0)
    wb = load_workbook(output)
    ws = wb.active
    ws.insert_rows(1, amount=5)

    # Logo y encabezados
    logo_path = os.path.join(settings.BASE_DIR, "static", "img", "logo-olympo.jpeg")
    if os.path.exists(logo_path):
        img = XLImage(logo_path)
        img.width = 120
        img.height = 120
        ws.add_image(img, "A1")

    # Títulos
    ws["C1"] = "Escuela Deportiva OLYMPO"
    ws["C2"] = "Reporte de Entrenadores"
    ws["C1"].font = Font(size=18, bold=True)
    ws["C2"].font = Font(size=14, bold=True)
    ws["C1"].alignment = Alignment(vertical="center")
    ws["C2"].alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 35
    ws.row_dimensions[2].height = 28

    # Estilo encabezado tabla
    header_fill = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")
    for col in range(1, ws.max_column + 1):
        cell = ws.cell(row=6, column=col)  # encabezados en fila 6
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.fill = header_fill

    # Ajustar anchos de columna dinámicamente + alineación diferenciada
    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        col_name = ws.cell(row=6, column=col[0].column).value  # nombre de la columna

        for cell in col:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))

            # 🔹 Ajustar alineación según la columna
            if col_name in ["Cédula", "Edad", "Teléfono"]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

        # 🔹 Ajustes más finos: menos ancho para "Edad"
        if col_name == "Edad":
            adjusted_width = 8
        else:
            adjusted_width = (max_length + 4) if max_length < 40 else 40

        ws.column_dimensions[col_letter].width = adjusted_width

    final_output = io.BytesIO()
    wb.save(final_output)
    final_output.seek(0)

    response = HttpResponse(
        final_output,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="reporte_entrenadores.xlsx"'
    return response

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_entrenadores_pdf(request):
    # Traer entrenadores y sus equipos
    entrenadores = (
        Entrenador.objects
        .all()
        .prefetch_related(Prefetch('equipo_set'))
    )

    buffer = BytesIO()

    # Márgenes altos para dejar espacio al encabezado
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=40, rightMargin=40,
        topMargin=120, bottomMargin=40
    )

    # Estilos
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TablaBody", fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="TablaBodyLeft", fontSize=8, leading=10, alignment=0))
    styles.add(ParagraphStyle(name="TablaBodyCenter", fontSize=8, leading=10, alignment=1))

    # 🔹 Ajuste de columnas (quitamos el correo)
    col_widths = [130, 70, 35, 80, 150]
    headers = ["Nombre y Apellido", "Cédula", "Edad", "Teléfono", "Equipos Dirigidos"]

    # Datos de la tabla
    data = [headers]
    for e in entrenadores:
        # Lista de equipos (solo nombres)
        equipos_list = [eq.nombre for eq in e.equipo_set.all() if getattr(eq, 'nombre', '')]
        equipos_txt = ", ".join(equipos_list) if equipos_list else "—"

        fila = [
            Paragraph(f"{e.nombre} {e.apellido}", styles["TablaBodyLeft"]),
            Paragraph(str(e.cedula or "—"), styles["TablaBodyCenter"]),
            Paragraph(str(getattr(e, "edad", "")), styles["TablaBodyCenter"]),
            Paragraph(str(e.telefono or "—"), styles["TablaBodyCenter"]),
            Paragraph(equipos_txt, styles["TablaBodyLeft"]),
        ]
        data.append(fila)

    # Tabla
    table = Table(data, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),

        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("VALIGN", (0, 1), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),

        ("ALIGN", (1, 1), (1, -1), "CENTER"),  # Cédula
        ("ALIGN", (2, 1), (2, -1), "CENTER"),  # Edad
        ("ALIGN", (3, 1), (3, -1), "CENTER"),  # Teléfono

        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor("#F7F9FA")]),
    ]))

    elements = [table]

    logo_path = os.path.join(settings.BASE_DIR, "static", "img", "logo-olympo.jpeg")

    # Encabezado / Pie
    def on_page(canvas, doc_):
        w, h = letter
        x = 40

        # Logo más grande
        if os.path.exists(logo_path):
            canvas.drawImage(logo_path, x, h - 100, width=75, height=75, preserveAspectRatio=True)

        # Títulos más grandes
        canvas.setFont("Helvetica-Bold", 18)
        canvas.setFillColor(colors.HexColor("#2C3E50"))
        canvas.drawString(x + 85, h - 55, "Escuela Deportiva OLYMPO")
        canvas.setFont("Helvetica", 14)
        canvas.setFillColor(colors.black)
        canvas.drawString(x + 85, h - 75, "Reporte de Entrenadores")

        # Línea de separación
        canvas.setStrokeColor(colors.HexColor("#2C3E50"))
        canvas.setLineWidth(1)
        canvas.line(40, h - 110, w - 40, h - 110)

        # Pie
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.black)
        canvas.drawString(40, 30, f"Exportado: {fecha}")
        canvas.drawRightString(w - 40, 30, f"Página {doc_.page}")

    doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)

    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename="reporte_entrenadores.pdf")

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_campeonatos(request):
    tipo = request.GET.get("tipo", "").strip()
    fecha_inicio_desde = request.GET.get("fecha_inicio_desde", "").strip()
    fecha_inicio_hasta = request.GET.get("fecha_inicio_hasta", "").strip()

    campeonatos = Campeonato.objects.all().order_by('-anio', 'nombre')

    if tipo:
        campeonatos = campeonatos.filter(tipo=tipo)

    # parse_date devuelve None si la cadena no es válida
    if fecha_inicio_desde:
        fd = parse_date(fecha_inicio_desde)
        if fd:
            campeonatos = campeonatos.filter(fecha_inicio__gte=fd)

    if fecha_inicio_hasta:
        fh = parse_date(fecha_inicio_hasta)
        if fh:
            campeonatos = campeonatos.filter(fecha_inicio__lte=fh)

    # PAGINACIÓN — 10 por página (ajusta si quieres)
    paginator = Paginator(campeonatos, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "tipo": tipo,
        "fecha_inicio_desde": fecha_inicio_desde,
        "fecha_inicio_hasta": fecha_inicio_hasta,
    }
    return render(request, "reportes/reporte_campeonatos.html", context)

# ========== EXPORTACIÓN PDF ==========
@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_campeonatos_pdf(request):
    tipo = request.GET.get("tipo", "").strip()
    fecha_inicio_desde = request.GET.get("fecha_inicio_desde", "").strip()
    fecha_inicio_hasta = request.GET.get("fecha_inicio_hasta", "").strip()

    campeonatos = Campeonato.objects.all()

    if tipo:
        campeonatos = campeonatos.filter(tipo=tipo)
    if fecha_inicio_desde:
        campeonatos = campeonatos.filter(fecha_inicio__gte=fecha_inicio_desde)
    if fecha_inicio_hasta:
        campeonatos = campeonatos.filter(fecha_inicio__lte=fecha_inicio_hasta)

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 40
    page_number = 1

    # Ajuste de columnas (incluyendo descripción)
    col_widths = [120, 70, 50, 80, 150]  
    headers = ["Nombre", "Tipo", "Año", "Fecha Inicio", "Descripción"]

    def encabezado(pagina_inicial=False):
        nonlocal y
        x = 40

        if pagina_inicial:
            # Logo
            logo_path = os.path.join(settings.BASE_DIR, "static", "img", "logo-olympo.jpeg")
            if os.path.exists(logo_path):
                logo = ImageReader(logo_path)
                p.drawImage(logo, x, height - 100, width=80, height=80)

            # Título
            p.setFont("Helvetica-Bold", 16)
            p.drawString(x + 90, height - 50, "Escuela Deportiva OLYMPO")
            p.setFont("Helvetica", 12)
            p.drawString(x + 90, height - 70, "Reporte de Campeonatos")

            # Línea separadora debajo del título y logo
            p.line(40, height - 110, width - 40, height - 110)

            y = height - 130  # bajar bien para empezar tabla
        else:
            y = height - 60  # reiniciar margen superior para las demás páginas

        # Encabezados de tabla (siempre dibujar)
        p.setFont("Helvetica-Bold", 8)
        curr_x = x
        for i, header in enumerate(headers):
            p.drawString(curr_x, y, header)
            curr_x += col_widths[i]
        y -= 16
        p.setFont("Helvetica", 7)

    def pie_pagina():
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
        p.setFont("Helvetica", 7)
        p.drawRightString(width - 40, 25, f"Página {page_number}")
        p.drawString(40, 25, f"Exportado: {fecha}")

    # Primer encabezado
    encabezado(pagina_inicial=True)

    # Datos
    for c in campeonatos:
        fila = [
            c.nombre,
            c.get_tipo_display(),
            c.anio,
            c.fecha_inicio.strftime("%d/%m/%Y") if c.fecha_inicio else "—",
            (c.descripcion[:50] + "...") if c.descripcion and len(c.descripcion) > 50 else (c.descripcion or "—"),
        ]
        curr_x = 40
        for i, dato in enumerate(fila):
            p.drawString(curr_x, y, str(dato))
            curr_x += col_widths[i]
        y -= 12

        # Salto de página
        if y < 50:
            pie_pagina()
            p.showPage()
            page_number += 1
            encabezado(pagina_inicial=False)  # <=== ahora siempre vuelve a dibujar encabezados

    pie_pagina()
    p.save()
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename="reporte_campeonatos.pdf")


# ========== EXPORTACIÓN EXCEL ==========
@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_campeonatos_excel(request):
    tipo = request.GET.get("tipo", "").strip()
    fecha_inicio_desde = request.GET.get("fecha_inicio_desde", "").strip()
    fecha_inicio_hasta = request.GET.get("fecha_inicio_hasta", "").strip()

    campeonatos = Campeonato.objects.all()
    if tipo:
        campeonatos = campeonatos.filter(tipo=tipo)
    if fecha_inicio_desde:
        campeonatos = campeonatos.filter(fecha_inicio__gte=fecha_inicio_desde)
    if fecha_inicio_hasta:
        campeonatos = campeonatos.filter(fecha_inicio__lte=fecha_inicio_hasta)

    data = []
    for c in campeonatos:
        data.append({
            "Nombre": c.nombre,
            "Tipo": c.get_tipo_display(),
            "Año": c.anio,
            "Fecha Inicio": c.fecha_inicio.strftime("%d/%m/%Y") if c.fecha_inicio else "—",
            "Descripción": c.descripcion or "—",
        })

    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Campeonatos")

    output.seek(0)
    wb = load_workbook(output)
    ws = wb.active

    # Insertamos espacio para que la tabla no choque con el logo/título
    ws.insert_rows(1, amount=7)  # antes 7 → subimos una fila la tabla

    # Logo
    logo_path = os.path.join(settings.BASE_DIR, "static", "img", "logo-olympo.jpeg")
    if os.path.exists(logo_path):
        img = XLImage(logo_path)
        img.width = 120
        img.height = 120
        ws.add_image(img, "A1")

    # Títulos (más abajo para mejor alineación)
    ws["C2"] = "Escuela Deportiva OLYMPO"
    ws["C3"] = "Reporte de Campeonatos"
    ws["C2"].font = Font(size=18, bold=True)
    ws["C3"].font = Font(size=14, bold=True)

    # Encabezado tabla (fila 7 ahora)
    header_fill = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")
    for col in range(1, ws.max_column + 1):
        cell = ws.cell(row=8, column=col)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.fill = header_fill

    # Ajuste de ancho automático pero limitado a 40
    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))
            cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[col_letter].width = min(max_length + 4, 40)

    # Exportación final
    final_output = io.BytesIO()
    wb.save(final_output)
    final_output.seek(0)

    response = HttpResponse(
        final_output,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="reporte_campeonatos.xlsx"'
    return response

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_partidos(request):
    fecha_desde = request.GET.get("fecha_desde", "").strip()
    fecha_hasta = request.GET.get("fecha_hasta", "").strip()
    campeonato_id = request.GET.get("campeonato", "").strip()
    estado = request.GET.get("estado", "").strip()
    equipo_id = request.GET.get("equipo", "").strip()
    ganador = request.GET.get("ganador", "").strip()
    export = request.GET.get("export", "").strip()

    partidos = Partido.objects.select_related("equipo_local", "campeonato").order_by("-fecha", "-hora")

    # Aplicar filtros
    if fecha_desde:
        partidos = partidos.filter(fecha__gte=parse_date(fecha_desde))
    if fecha_hasta:
        partidos = partidos.filter(fecha__lte=parse_date(fecha_hasta))
    if campeonato_id:
        partidos = partidos.filter(campeonato_id=campeonato_id)
    if estado:
        partidos = partidos.filter(estado=estado)
    if equipo_id:
        partidos = partidos.filter(equipo_local_id=equipo_id)
    if ganador:
        if ganador == "local":
            partidos = partidos.filter(ganador="local")
        else:
            partidos = partidos.filter(ganador="externo", equipo_externo=ganador)

    # ✅ Exportación PDF
    if export == "pdf":
        return exportar_partidos_pdf(partidos)

    # ✅ Exportación Excel
    if export == "excel":
        return exportar_partidos_excel(partidos)

    # Paginación normal
    paginator = Paginator(partidos, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Opciones dinámicas
    equipos = Equipo.objects.all()
    campeonatos = Campeonato.objects.all()
    estados = Partido.ESTADOS
    ganadores = ["local"]
    ganadores_externos = (
        Partido.objects.filter(ganador="externo").values_list("equipo_externo", flat=True).distinct()
    )
    ganadores += list(ganadores_externos)

    context = {
        "page_obj": page_obj,
        "equipos": equipos,
        "campeonatos": campeonatos,
        "estados": estados,
        "ganadores": ganadores,
        "filtros": {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "campeonato": campeonato_id,
            "estado": estado,
            "equipo": equipo_id,
            "ganador": ganador,
        },
    }
    return render(request, "reportes/reporte_partidos.html", context)

def exportar_partidos_pdf(partidos):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 40
    page_number = 1

    # ✅ Ajuste de anchos de columna
    col_widths = [
        50, 65, 55, 75, 55, 42, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20
    ]

    headers = [
        "Fecha", "Local", "Externo", "Campeonato", "Estado", "Ganador",
        "S1L", "S1X", "S2L", "S2X", "S3L", "S3X", "S4L", "S4X", "S5L", "S5X"
    ]

    def encabezado(pagina_inicial=False):
        nonlocal y
        x = 40

        if pagina_inicial:
            # ✅ Logo
            logo_path = os.path.join("static", "img", "logo-olympo.jpeg")
            if os.path.exists(logo_path):
                logo = ImageReader(logo_path)
                p.drawImage(logo, x, height - 100, width=70, height=70)

            # ✅ Título
            p.setFont("Helvetica-Bold", 14)
            p.drawString(x + 90, height - 50, "Escuela Deportiva OLYMPO")
            p.setFont("Helvetica", 12)
            p.drawString(x + 90, height - 70, "Reporte de Partidos")

            # ✅ Línea separadora
            p.line(40, height - 110, width - 40, height - 110)
            y = height - 130
        else:
            y = height - 60

        # ✅ Encabezados
        p.setFont("Helvetica-Bold", 7)
        curr_x = x
        for i, header in enumerate(headers):
            p.drawString(curr_x, y, header)
            curr_x += col_widths[i]
        y -= 14
        p.setFont("Helvetica", 6.5)

    def pie_pagina():
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
        p.setFont("Helvetica", 7)
        p.drawRightString(width - 40, 25, f"Página {page_number}")
        p.drawString(40, 25, f"Exportado: {fecha}")

    # ✅ Primer encabezado
    encabezado(pagina_inicial=True)

    # ✅ Filas
    for partido in partidos:
        fila = [
            partido.fecha.strftime("%d/%m/%Y"),
            partido.equipo_local.nombre if partido.equipo_local else "",
            partido.equipo_externo,
            partido.campeonato.nombre if partido.campeonato else "",
            partido.estado.capitalize(),
            "Local" if partido.ganador == "local" else ("Externo" if partido.ganador == "externo" else ""),
            partido.set1_local or "", partido.set1_externo or "",
            partido.set2_local or "", partido.set2_externo or "",
            partido.set3_local or "", partido.set3_externo or "",
            partido.set4_local or "", partido.set4_externo or "",
            partido.set5_local or "", partido.set5_externo or "",
        ]

        curr_x = 40
        for i, dato in enumerate(fila):
            p.drawString(curr_x, y, str(dato))
            curr_x += col_widths[i]
        y -= 12

        # ✅ Salto de página si se llena
        if y < 50:
            pie_pagina()
            p.showPage()
            page_number += 1
            encabezado(pagina_inicial=False)

    # ✅ Pie final
    pie_pagina()
    p.save()
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename="Reporte_Partidos.pdf")

def exportar_partidos_excel(partidos):
    # ✅ Construcción de datos en lista de dicts
    data = []
    for p in partidos:
        data.append({
            "Fecha": p.fecha.strftime("%d/%m/%Y") if p.fecha else "—",
            "Hora": p.hora.strftime("%H:%M") if p.hora else "—",
            "Local": p.equipo_local.nombre if p.equipo_local else "—",
            "Externo": p.equipo_externo or "—",
            "Campeonato": p.campeonato.nombre if p.campeonato else "—",
            "Estado": p.get_estado_display() if hasattr(p, "get_estado_display") else p.estado,
            "Ganador": "Local" if p.ganador == "local" else (p.equipo_externo if p.ganador == "externo" else "—"),
            "S1L": p.set1_local or "", "S1X": p.set1_externo or "",
            "S2L": p.set2_local or "", "S2X": p.set2_externo or "",
            "S3L": p.set3_local or "", "S3X": p.set3_externo or "",
            "S4L": p.set4_local or "", "S4X": p.set4_externo or "",
            "S5L": p.set5_local or "", "S5X": p.set5_externo or "",
        })

    df = pd.DataFrame(data)

    # ✅ Generamos archivo base con pandas
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Partidos")

    output.seek(0)
    wb = load_workbook(output)
    ws = wb.active

    # ✅ Insertamos espacio para título y logo
    ws.insert_rows(1, amount=7)

    # ✅ Agregar logo
    logo_path = os.path.join(settings.BASE_DIR, "static", "img", "logo-olympo.jpeg")
    if os.path.exists(logo_path):
        try:
            img = XLImage(logo_path)
            img.width = 120
            img.height = 120
            ws.add_image(img, "A1")
        except Exception as e:
            print(f"Error cargando logo: {e}")

    # ✅ Títulos
    ws["C2"] = "Escuela Deportiva OLYMPO"
    ws["C3"] = "Reporte de Partidos"
    ws["C4"] = f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ws["C2"].font = Font(size=18, bold=True)
    ws["C3"].font = Font(size=14, bold=True)
    ws["C4"].font = Font(size=10, italic=True)

    # ✅ Estilo para encabezado
    header_fill = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")
    for col in range(1, ws.max_column + 1):
        cell = ws.cell(row=8, column=col)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.fill = header_fill

    # ✅ Ajuste dinámico de ancho
    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))
            cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[col_letter].width = min(max_length + 4, 40)

    # ✅ Preparar respuesta
    final_output = io.BytesIO()
    wb.save(final_output)
    final_output.seek(0)

    response = HttpResponse(
        final_output,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="Reporte_Partidos.xlsx"'
    return response

@admin.register(Atleta)
class AtletaAdmin(admin.ModelAdmin):
    list_display = ('nombre','apellido','categoria','cedula')
    # Bloquear add/change/delete a NO admin (y no superuser)
    def has_add_permission(self, request):    return es_admin(request.user) or request.user.is_superuser
    def has_change_permission(self, request, obj=None): return es_admin(request.user) or request.user.is_superuser
    def has_delete_permission(self, request, obj=None): return es_admin(request.user) or request.user.is_superuser

@admin.register(Entrenador)
class EntrenadorAdmin(admin.ModelAdmin):
    list_display = ('nombre','apellido','cedula','telefono')
    def has_add_permission(self, request):    return es_admin(request.user) or request.user.is_superuser
    def has_change_permission(self, request, obj=None): return es_admin(request.user) or request.user.is_superuser
    def has_delete_permission(self, request, obj=None): return es_admin(request.user) or request.user.is_superuser

admin.site.register(Equipo)
admin.site.register(Campeonato)
admin.site.register(Partido)
admin.site.register(Estadistica)
admin.site.register(Mensualidad)

@user_passes_test(es_admin)
def lista_administradores(request):
    administradores = Administrador.objects.all().order_by("apellido")
    paginator = Paginator(administradores, 8)  # 5 admins por página
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
            # Guardar administrador sin usuario todavía
            administrador = administrador_form.save(commit=False)

            # Datos del usuario
            username = usuario_form.cleaned_data['username']
            password = usuario_form.cleaned_data['password']
            email = usuario_form.cleaned_data['email']

            # Crear usuario + asignar grupo automáticamente
            crear_usuario_para_administrador(administrador, username, password, email)

            return redirect('lista_administradores')
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
    return render(request, 'administradores/detalle.html', {
        'administrador': administrador
    })

@user_passes_test(es_admin)
def editar_administrador(request, administrador_id):
    administrador = get_object_or_404(Administrador, id=administrador_id)
    usuario = administrador.usuario  

    if request.method == "POST":
        form = AdministradorForm(request.POST, instance=administrador)
        usuario_form = UsuarioForm(request.POST, instance=usuario)

        if form.is_valid() and usuario_form.is_valid():
            form.save()
            usuario_form.save()  # ya maneja contraseña y estado
            return redirect("detalle_administrador", administrador.id)
    else:
        form = AdministradorForm(instance=administrador)
        usuario_form = UsuarioForm(instance=usuario)

    return render(
        request,
        "administradores/editar.html",
        {"form": form, "usuario_form": usuario_form, "administrador": administrador},
    )

@user_passes_test(es_admin)
def eliminar_administrador(request, administrador_id):
    administrador = get_object_or_404(Administrador, id=administrador_id)
    if request.method == "POST":
        administrador.delete()
        return redirect("lista_administradores")
    return render(request, "administradores/eliminar.html", {"administrador": administrador})

@user_passes_test(es_admin)
def lista_usuarios(request):
    rol_filtro = request.GET.get('rol', '')
    estado_filtro = request.GET.get('estado', '')
    nombre_filtro = request.GET.get('nombre', '')

    usuarios = []

    # --- Entrenadores ---
    for e in Entrenador.objects.select_related('user'):
        if not e.user:
            continue
        usuarios.append({
            'id': e.id,
            'nombre': e.nombre,
            'apellido': e.apellido,
            'usuario': e.user.username,
            'email': e.user.email,
            'rol': 'Entrenador',
            'estado': 'Activo' if e.user.is_active else 'Inactivo',
        })

    # --- Atletas ---
    for a in Atleta.objects.select_related('user'):
        if not a.user:
            continue
        usuarios.append({
            'id': a.id,
            'nombre': a.nombre,
            'apellido': a.apellido,
            'usuario': a.user.username,
            'email': a.user.email,
            'rol': 'Atleta',
            'estado': 'Activo' if a.user.is_active else 'Inactivo',
        })

    # --- Administradores ---
    for ad in Administrador.objects.select_related('usuario'):
        if not ad.usuario:
            continue
        usuarios.append({
            'id': ad.id,
            'nombre': ad.nombre,
            'apellido': ad.apellido,
            'usuario': ad.usuario.username,
            'email': ad.usuario.email,
            'rol': 'Administrador',
            'estado': 'Activo' if ad.usuario.is_active else 'Inactivo',
        })

    # --- FILTROS ---
    if rol_filtro:
        usuarios = [u for u in usuarios if u['rol'] == rol_filtro]
    if estado_filtro:
        usuarios = [u for u in usuarios if u['estado'] == estado_filtro]
    if nombre_filtro:
        usuarios = [u for u in usuarios if nombre_filtro.lower() in u['nombre'].lower()]

    # --- PAGINACIÓN ---
    paginator = Paginator(usuarios, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'usuarios/lista.html', {
        'page_obj': page_obj,
        'rol_filtro': rol_filtro,
        'estado_filtro': estado_filtro,
        'nombre_filtro': nombre_filtro,
    })