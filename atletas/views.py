from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .forms import AtletaForm, EstadisticaForm, EntrenadorForm, CampeonatoForm, PartidoForm, EquipoForm, UsuarioForm, AdministradorForm
from django.core.paginator import Paginator
from datetime import date
from django.views.decorators.http import require_POST, require_http_methods
from django.db.models import Sum, Count, Q, Prefetch
from django.db.models.functions import ExtractYear
from django.contrib import messages
from django.contrib.auth.models import User
from django.db import models
from django.db import IntegrityError, transaction
from django.utils import timezone
from datetime import timedelta, datetime
from django.contrib.auth import authenticate, login
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from django.http import FileResponse, HttpResponse
import io
import pandas as pd
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
from django.utils.formats import date_format
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.urls import reverse
from decimal import Decimal, ROUND_HALF_UP
from .models import TasaCambio
from .models import (
    Atleta,
    Mensualidad,
    Estadistica,
    Entrenador,
    Campeonato,
    Partido,
    Equipo,
    Administrador,
    PagoMensualidad,
    TarifaMensual,
    Pago,
)
from .services import (
    crear_usuario_para_atleta,
    crear_usuario_para_administrador,
    crear_usuario_para_entrenador,
    eliminar_usuario_sin_perfil,
    registrar_pago,
    obtener_tasa_actual,
    obtener_tarifa_mensual,
    TasaCambioNoDisponible,
    anular_pago,
    exonerar_mensualidad,
    quitar_exoneracion,
)

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
            try:
                crear_usuario_para_atleta(atleta, username, password, email)
            except IntegrityError:
                usuario_form.add_error(
                    'username',
                    'Ya existe una cuenta con este nombre de usuario.'
                )
            else:
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
        usuario = atleta.user

        with transaction.atomic():
            atleta.delete()
            eliminar_usuario_sin_perfil(usuario)

        return redirect('lista_atletas')

    return render(request, 'atletas/eliminar_atleta.html', {'atleta': atleta})

@user_passes_test(es_admin)
@require_POST
def guardar_tarifa_mensual(request):
    """
    Crea o actualiza una tarifa a partir de un mes determinado.

    Ejemplo:
    $8 desde enero 2027.

    Los períodos anteriores conservan sus tarifas anteriores.
    """

    monto_texto = request.POST.get(
        "monto_usd",
        ""
    ).strip()

    tolerancia_texto = request.POST.get(
        "tolerancia_usd",
        ""
    ).strip()

    periodo_texto = request.POST.get(
        "vigente_desde",
        ""
    ).strip()

    try:

        monto = Decimal(
            monto_texto
        ).quantize(
            Decimal("0.01")
        )

        tolerancia = Decimal(
            tolerancia_texto
        ).quantize(
            Decimal("0.01")
        )

    except Exception:

        messages.error(
            request,
            "El monto o la tolerancia no son válidos."
        )

        return redirect(
            "administracion"
        )

    if monto <= Decimal("0.00"):

        messages.error(
            request,
            "La cuota debe ser mayor que cero."
        )

        return redirect(
            "administracion"
        )

    if tolerancia < Decimal("0.00"):

        messages.error(
            request,
            "La tolerancia no puede ser negativa."
        )

        return redirect(
            "administracion"
        )

    if tolerancia >= monto:

        messages.error(
            request,
            (
                "La tolerancia debe ser menor "
                "que el valor de la mensualidad."
            )
        )

        return redirect(
            "administracion"
        )

    try:

        año_texto, mes_texto = (
            periodo_texto.split("-")
        )

        año = int(
            año_texto
        )

        mes = int(
            mes_texto
        )

        vigente_desde = date(
            año,
            mes,
            1
        )

    except (
        ValueError,
        TypeError,
    ):

        messages.error(
            request,
            "Debe seleccionar un período válido."
        )

        return redirect(
            "administracion"
        )

    tarifa, creada = (
        TarifaMensual.objects
        .update_or_create(
            vigente_desde=vigente_desde,
            defaults={
                "monto_usd":
                    monto,
                "tolerancia_usd":
                    tolerancia,
            },
        )
    )

    if creada:

        messages.success(
            request,
            (
                "Nueva tarifa registrada: "
                f"${tarifa.monto_usd:.2f} "
                f"desde {mes:02d}/{año}."
            )
        )

    else:

        messages.success(
            request,
            (
                "Tarifa actualizada: "
                f"${tarifa.monto_usd:.2f} "
                f"desde {mes:02d}/{año}."
            )
        )

    return redirect(
        "administracion"
    )

@user_passes_test(es_admin)
@require_POST
def registrar_pago_administracion(request):
    """
    Registra una transacción real de pago.

    Los períodos se reciben como YYYY-MM.

    Si un período antiguo todavía no tiene una Mensualidad,
    se crea únicamente cuando realmente se está registrando
    un pago para dicho período.
    """

    atleta_id = request.POST.get(
        "atleta_id"
    )

    periodos = request.POST.getlist(
        "periodos"
    )

    moneda = request.POST.get(
        "moneda",
        ""
    ).strip().upper()

    monto_total = request.POST.get(
        "monto_total",
        ""
    ).strip()

    metodo = request.POST.get(
        "metodo",
        ""
    ).strip()

    referencia = request.POST.get(
        "referencia",
        ""
    ).strip()

    observacion = request.POST.get(
        "observacion",
        ""
    ).strip()

    fecha_pago_texto = request.POST.get(
        "fecha_pago",
        ""
    ).strip()

    mes_retorno = request.POST.get(
        "mes_retorno"
    )

    año_retorno = request.POST.get(
        "año_retorno"
    )

    categoria_retorno = request.POST.get(
        "categoria_retorno",
        ""
    ).strip()

    def volver_administracion():

        parametros = []

        if mes_retorno:
            parametros.append(
                f"mes={mes_retorno}"
            )

        if año_retorno:
            parametros.append(
                f"año={año_retorno}"
            )

        if categoria_retorno:

            from urllib.parse import quote

            parametros.append(
                "categoria="
                + quote(
                    categoria_retorno
                )
            )

        url = reverse(
            "administracion"
        )

        if parametros:
            url += (
                "?"
                + "&".join(parametros)
            )

        return redirect(url)

    if not atleta_id:

        messages.error(
            request,
            "Debe seleccionarse un atleta."
        )

        return volver_administracion()

    if not periodos:

        messages.error(
            request,
            "Debe seleccionar al menos un mes."
        )

        return volver_administracion()

    if not monto_total:

        messages.error(
            request,
            "Debe ingresar el monto recibido."
        )

        return volver_administracion()

    atleta = get_object_or_404(
        Atleta,
        pk=atleta_id
    )

    # -----------------------------------------
    # FECHA REAL DEL PAGO
    # -----------------------------------------

    fecha_pago = timezone.localdate()

    if fecha_pago_texto:

        fecha_parseada = parse_date(
            fecha_pago_texto
        )

        if fecha_parseada is None:

            messages.error(
                request,
                "La fecha del pago no es válida."
            )

            return volver_administracion()

        fecha_pago = fecha_parseada

    try:

        with transaction.atomic():

            mensualidades_ids = []

            periodos_unicos = set()

            for periodo in periodos:

                if periodo in periodos_unicos:
                    continue

                periodos_unicos.add(
                    periodo
                )

                try:

                    año_texto, mes_texto = (
                        periodo.split("-")
                    )

                    año = int(
                        año_texto
                    )

                    mes = int(
                        mes_texto
                    )

                except (
                    ValueError,
                    TypeError,
                ) as error:

                    raise ValidationError(
                        "Se recibió un período inválido."
                    ) from error

                if mes < 1 or mes > 12:

                    raise ValidationError(
                        "Se recibió un mes inválido."
                    )

                tarifa = obtener_tarifa_mensual(
                    año,
                    mes
                )

                if tarifa is None:

                    raise ValidationError(
                        (
                            "No existe una tarifa configurada "
                            f"para {mes:02d}/{año}."
                        )
                    )

                mensualidad, _ = (
                    Mensualidad.objects
                    .get_or_create(
                        atleta=atleta,
                        año=año,
                        mes=mes,
                        defaults={
                            "monto_pagado":
                                Decimal("0.00"),
                            "exonerado":
                                False,
                        },
                    )
                )

                mensualidades_ids.append(
                    mensualidad.id
                )

            pago = registrar_pago(
                atleta=atleta,
                mensualidades=mensualidades_ids,
                moneda=moneda,
                monto_total=monto_total,
                usuario=request.user,
                metodo=metodo,
                referencia=referencia,
                observacion=observacion,
                fecha_pago=fecha_pago,
            )

    except TasaCambioNoDisponible:

        messages.error(
            request,
            (
                "No fue posible obtener una tasa BCV "
                "y tampoco existe una tasa guardada."
            )
        )

        return volver_administracion()

    except ValidationError as error:

        if hasattr(
            error,
            "message_dict"
        ):

            mensajes = []

            for errores in (
                error.message_dict.values()
            ):
                mensajes.extend(
                    errores
                )

        else:
            mensajes = error.messages

        for mensaje in mensajes:

            messages.error(
                request,
                mensaje
            )

        return volver_administracion()

    messages.success(
        request,
        (
            "Pago registrado correctamente. "
            f"Equivalente aproximado: "
            f"${pago.equivalente_usd:.2f}"
        )
    )

    return volver_administracion()

@user_passes_test(es_admin)
@require_POST
def actualizar_tasa_bcv(request):
    """
    Fuerza una nueva consulta de la tasa BCV.

    Si existe una tasa manual y la consulta automática
    falla, la tasa manual continúa almacenada y el
    administrador recibe el aviso correspondiente.
    """

    try:
        tasa = obtener_tasa_actual(
            forzar_actualizacion=True
        )

    except TasaCambioNoDisponible:
        messages.error(
            request,
            (
                "No fue posible actualizar la tasa desde BCV. "
                "La última tasa guardada continuará disponible."
            )
        )

        return redirect(
            "administracion"
        )

    messages.success(
        request,
        (
            "Tasa BCV actualizada correctamente: "
            f"Bs {tasa.tasa_bs_usd:.2f} / USD "
            f"({tasa.fecha_valor.strftime('%d/%m/%Y')})."
        )
    )

    return redirect(
        "administracion"
    )


@user_passes_test(es_admin)
@require_POST
def guardar_tasa_manual(request):
    """
    Registra manualmente una tasa Bs/USD.

    La tasa manual pasa a ser la tasa activa hasta que
    una actualización automática desde BCV se complete
    correctamente.
    """

    tasa_texto = request.POST.get(
        "tasa_bs_usd",
        ""
    ).strip()

    fecha_texto = request.POST.get(
        "fecha_valor",
        ""
    ).strip()

    observacion = request.POST.get(
        "observacion",
        ""
    ).strip()

    try:
        tasa = Decimal(
            tasa_texto
        ).quantize(
            Decimal("0.000001")
        )

    except Exception:
        messages.error(
            request,
            "La tasa ingresada no es válida."
        )

        return redirect(
            "administracion"
        )

    if tasa <= Decimal("0.00"):
        messages.error(
            request,
            "La tasa debe ser mayor que cero."
        )

        return redirect(
            "administracion"
        )

    fecha_valor = timezone.localdate()

    if fecha_texto:
        fecha_parseada = parse_date(
            fecha_texto
        )

        if fecha_parseada is None:
            messages.error(
                request,
                "La fecha valor no es válida."
            )

            return redirect(
                "administracion"
            )

        fecha_valor = fecha_parseada

    tasa_manual = TasaCambio.objects.create(
        tasa_bs_usd=tasa,
        fecha_valor=fecha_valor,
        fuente="BCV - Registro manual",
        origen="manual",
        observacion=(
            observacion
            or (
                "Tasa registrada manualmente "
                "por un administrador."
            )
        ),
    )

    messages.success(
        request,
        (
            "Tasa manual registrada correctamente: "
            f"Bs {tasa_manual.tasa_bs_usd:.2f} / USD."
        )
    )

    return redirect(
        "administracion"
    )

@user_passes_test(es_admin)
@require_POST
def anular_pago_administracion(
    request,
    pago_id,
):
    """
    Anula una transacción financiera conservando
    completamente su historial.
    """

    pago = get_object_or_404(
        Pago,
        pk=pago_id
    )

    motivo = request.POST.get(
        "motivo_anulacion",
        ""
    ).strip()

    siguiente = request.POST.get(
        "next",
        ""
    ).strip()

    try:

        pago = anular_pago(
            pago=pago,
            usuario=request.user,
            motivo=motivo,
        )

    except ValidationError as error:

        for mensaje in error.messages:

            messages.error(
                request,
                mensaje
            )

    else:

        messages.success(
            request,
            (
                f"Pago #{pago.id} "
                "anulado correctamente."
            )
        )

    if (
        siguiente
        and siguiente.startswith("/")
        and not siguiente.startswith("//")
    ):
        return redirect(
            siguiente
        )

    return redirect(
        "administracion"
    )

@user_passes_test(es_admin)
@require_POST
def exonerar_mensualidad_administracion(
    request,
    mensualidad_id,
):
    """
    Exonera una mensualidad concreta.
    """

    mensualidad = get_object_or_404(
        Mensualidad,
        pk=mensualidad_id,
    )

    motivo = request.POST.get(
        "motivo_exoneracion",
        ""
    ).strip()

    siguiente = request.POST.get(
        "next",
        ""
    ).strip()

    try:

        mensualidad = exonerar_mensualidad(
            mensualidad=mensualidad,
            usuario=request.user,
            motivo=motivo,
        )

    except ValidationError as error:

        for mensaje in error.messages:

            messages.error(
                request,
                mensaje
            )

    else:

        messages.success(
            request,
            (
                f"{mensualidad.atleta.nombre} "
                f"{mensualidad.atleta.apellido} "
                f"ha sido exonerado(a) para "
                f"{mensualidad.mes:02d}/"
                f"{mensualidad.año}."
            )
        )

    if (
        siguiente
        and siguiente.startswith("/")
        and not siguiente.startswith("//")
    ):
        return redirect(
            siguiente
        )

    return redirect(
        "administracion"
    )


@user_passes_test(es_admin)
@require_POST
def quitar_exoneracion_administracion(
    request,
    mensualidad_id,
):
    """
    Retira la exoneración de una mensualidad.
    """

    mensualidad = get_object_or_404(
        Mensualidad,
        pk=mensualidad_id,
    )

    siguiente = request.POST.get(
        "next",
        ""
    ).strip()

    try:

        mensualidad = quitar_exoneracion(
            mensualidad
        )

    except ValidationError as error:

        for mensaje in error.messages:

            messages.error(
                request,
                mensaje
            )

    else:

        messages.success(
            request,
            (
                "Exoneración retirada correctamente "
                f"para {mensualidad.atleta.nombre} "
                f"{mensualidad.atleta.apellido}."
            )
        )

    if (
        siguiente
        and siguiente.startswith("/")
        and not siguiente.startswith("//")
    ):
        return redirect(
            siguiente
        )

    return redirect(
        "administracion"
    )

@user_passes_test(es_admin)
@require_POST
def exonerar_periodo_financiero(
    request,
    atleta_id,
):
    """
    Exonera un período directamente desde
    la ficha financiera del atleta.

    Si la mensualidad todavía no existe
    físicamente, se crea únicamente en el
    momento de realizar la exoneración.
    """

    atleta = get_object_or_404(
        Atleta,
        pk=atleta_id,
    )

    siguiente = (
        request.POST
        .get(
            "next",
            "",
        )
        .strip()
    )

    motivo = (
        request.POST
        .get(
            "motivo_exoneracion",
            "",
        )
        .strip()
    )


    # =========================================
    # VALIDAR AÑO Y MES
    # =========================================

    try:

        año = int(
            request.POST.get(
                "año"
            )
        )

        mes = int(
            request.POST.get(
                "mes"
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        messages.error(
            request,
            "El período seleccionado no es válido.",
        )

        if (
            siguiente
            and siguiente.startswith("/")
            and not siguiente.startswith("//")
        ):
            return redirect(
                siguiente
            )

        return redirect(
            "administracion"
        )


    if (
        año < 2000
        or año > 2100
        or mes < 1
        or mes > 12
    ):

        messages.error(
            request,
            "El período seleccionado no es válido.",
        )

        if (
            siguiente
            and siguiente.startswith("/")
            and not siguiente.startswith("//")
        ):
            return redirect(
                siguiente
            )

        return redirect(
            "administracion"
        )


    # =========================================
    # VERIFICAR QUE EXISTA TARIFA
    # =========================================

    tarifa = obtener_tarifa_mensual(
        año,
        mes,
    )


    if tarifa is None:

        messages.error(
            request,
            (
                "No se puede exonerar este período "
                "porque no tiene una tarifa configurada."
            ),
        )

        if (
            siguiente
            and siguiente.startswith("/")
            and not siguiente.startswith("//")
        ):
            return redirect(
                siguiente
            )

        return redirect(
            "administracion"
        )


    # =========================================
    # OBTENER O CREAR MENSUALIDAD
    # =========================================

    mensualidad, _ = (
        Mensualidad.objects
        .get_or_create(
            atleta=atleta,
            año=año,
            mes=mes,
            defaults={
                "monto_pagado":
                    Decimal("0.00"),

                "exonerado":
                    False,

                "en_control":
                    False,
            },
        )
    )


    # =========================================
    # EXONERAR
    # =========================================

    try:

        mensualidad = (
            exonerar_mensualidad(
                mensualidad=mensualidad,
                usuario=request.user,
                motivo=motivo,
            )
        )

    except ValidationError as error:

        for mensaje in error.messages:

            messages.error(
                request,
                mensaje,
            )

    else:

        messages.success(
            request,
            (
                f"{atleta.nombre} "
                f"{atleta.apellido} fue "
                f"exonerado(a) para "
                f"{mes:02d}/{año}."
            ),
        )


    # =========================================
    # REGRESAR
    # =========================================

    if (
        siguiente
        and siguiente.startswith("/")
        and not siguiente.startswith("//")
    ):

        return redirect(
            siguiente
        )


    return redirect(
        "administracion"
    )

@user_passes_test(es_admin)
def detalle_financiero_atleta(
    request,
    atleta_id,
):
    """
    Ficha financiera anual de un atleta.

    Muestra:
    - los 12 meses del año;
    - estado real de cada período;
    - cuota aplicable;
    - pagos activos;
    - pagos anulados;
    - bolívares realmente recibidos;
    - equivalente en USD;
    - saldo;
    - exoneraciones;
    - cantidad de movimientos.
    """

    atleta = get_object_or_404(
        Atleta,
        pk=atleta_id,
    )

    hoy = timezone.localdate()


    # =========================================
    # AÑO SELECCIONADO
    # =========================================

    try:

        año_seleccionado = int(
            request.GET.get(
                "año",
                hoy.year,
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        año_seleccionado = (
            hoy.year
        )


    if not (
        2000
        <= año_seleccionado
        <= 2100
    ):

        año_seleccionado = (
            hoy.year
        )


    # =========================================
    # AÑOS DISPONIBLES
    # =========================================

    años_disponibles = set(

        Mensualidad.objects
        .filter(
            atleta=atleta
        )
        .values_list(
            "año",
            flat=True,
        )

    )

    años_disponibles.add(
        hoy.year
    )

    años_disponibles.add(
        año_seleccionado
    )

    años_disponibles = sorted(
        años_disponibles,
        reverse=True,
    )


    # =========================================
    # CARGAR MENSUALIDADES DEL AÑO
    # =========================================

    aplicaciones_qs = (

        PagoMensualidad.objects
        .select_related(
            "pago"
        )
        .prefetch_related(
            "pago__aplicaciones__mensualidad"
        )
        .order_by(
            "pago__fecha_pago",
            "pago__creado_en",
            "id",
        )

    )


    mensualidades = (

        Mensualidad.objects
        .filter(
            atleta=atleta,
            año=año_seleccionado,
        )
        .prefetch_related(

            Prefetch(
                "pagos",
                queryset=aplicaciones_qs,
            )

        )

    )


    mensualidades_por_mes = {

        mensualidad.mes:
            mensualidad

        for mensualidad
        in mensualidades

    }


    # =========================================
    # NOMBRES DE MESES
    # =========================================

    nombres_meses = {

        1: "Enero",
        2: "Febrero",
        3: "Marzo",
        4: "Abril",
        5: "Mayo",
        6: "Junio",
        7: "Julio",
        8: "Agosto",
        9: "Septiembre",
        10: "Octubre",
        11: "Noviembre",
        12: "Diciembre",

    }


    # =========================================
    # ACUMULADORES ANUALES
    # =========================================

    total_usd = Decimal(
        "0.0000"
    )

    total_bs = Decimal(
        "0.00"
    )


    al_dia = 0
    parciales = 0
    pendientes = 0
    exonerados = 0
    sin_registro = 0
    sin_tarifa = 0
    proximos = 0

    meses_gestionados = 0
    meses_cubiertos = 0


    periodos = []


    # =========================================
    # CONSTRUIR LOS 12 MESES
    # =========================================

    for mes in range(
        1,
        13,
    ):

        mensualidad = (
            mensualidades_por_mes
            .get(
                mes
            )
        )


        tarifa = (
            obtener_tarifa_mensual(
                año_seleccionado,
                mes,
            )
        )


        es_futuro = (

            (
                año_seleccionado,
                mes,
            )
            >
            (
                hoy.year,
                hoy.month,
            )

        )


        # =====================================
        # DATOS BASE
        # =====================================

        cuota_usd = (

            tarifa.monto_usd
            if tarifa
            else None

        )


        tolerancia_usd = (

            tarifa.tolerancia_usd
            if tarifa
            else None

        )


        pagado_usd = Decimal(
            "0.0000"
        )

        saldo_usd = None

        movimientos = []

        pagado_bs = Decimal(
            "0.00"
        )


        # =====================================
        # SI EXISTE MENSUALIDAD
        # =====================================

        if mensualidad:

            pagado_usd = (
                mensualidad
                .total_pagado_usd
            )


            # ---------------------------------
            # ESTADO REAL
            # ---------------------------------

            estado_codigo = (
                mensualidad
                .estado_codigo
            )


            # Un mes futuro sin ninguna gestión
            # debe verse como "Próximo".
            if (

                es_futuro

                and not mensualidad.en_control

                and not mensualidad.exonerado

                and pagado_usd
                    <= Decimal("0.00")

            ):

                estado_codigo = (
                    "proximo"
                )


            # ---------------------------------
            # SALDO
            # ---------------------------------

            if estado_codigo not in {
                "proximo",
                "sin_registro",
            }:

                saldo_usd = (
                    mensualidad
                    .saldo_pendiente_usd
                )


            # ---------------------------------
            # MOVIMIENTOS
            # ---------------------------------

            for aplicacion in (
                mensualidad
                .pagos
                .all()
            ):

                pago = aplicacion.pago


                if not pago:

                    continue

                # =================================
                # TODAS LAS MENSUALIDADES CUBIERTAS
                # POR ESTE PAGO
                # =================================

                aplicaciones_del_pago = []


                for otra_aplicacion in (
                    pago.aplicaciones.all()
                ):

                    otra_mensualidad = (
                        otra_aplicacion.mensualidad
                    )


                    if not otra_mensualidad:

                        continue


                    nombre_otro_mes = (
                        nombres_meses.get(
                            otra_mensualidad.mes,
                            str(otra_mensualidad.mes),
                        )
                    )


                    monto_aplicado_bs = Decimal(
                        "0.00"
                    )


                    # Si el pago fue realizado en bolívares,
                    # calculamos qué parte aproximada de esos
                    # bolívares corresponde a esta mensualidad.
                    if (

                        pago.moneda == "VES"

                        and pago.equivalente_usd

                        and pago.equivalente_usd
                            > Decimal("0.00")

                    ):

                        proporcion_aplicacion = (

                            otra_aplicacion
                            .monto_aplicado_usd

                            /

                            pago.equivalente_usd

                        )


                        monto_aplicado_bs = (

                            proporcion_aplicacion
                            *
                            pago.monto_total

                        ).quantize(

                            Decimal("0.01"),

                            rounding=ROUND_HALF_UP,

                        )


                    aplicaciones_del_pago.append({

                        "aplicacion_id":
                            otra_aplicacion.id,

                        "mensualidad_id":
                            otra_mensualidad.id,

                        "mes":
                            otra_mensualidad.mes,

                        "nombre_mes":
                            nombre_otro_mes,

                        "año":
                            otra_mensualidad.año,

                        "monto_aplicado_usd":
                            otra_aplicacion
                            .monto_aplicado_usd,

                        "monto_aplicado_bs":
                            monto_aplicado_bs,

                    })


                # Siempre mostrar las aplicaciones
                # ordenadas cronológicamente.
                aplicaciones_del_pago.sort(
                    key=lambda item: (
                        item["año"],
                        item["mes"],
                    )
                )

                aplicado_bs = Decimal(
                    "0.00"
                )


                # ---------------------------------
                # CALCULAR PARTE DEL PAGO EN BS
                # ---------------------------------

                if (

                    pago.estado
                    == "activo"

                    and pago.moneda
                    == "VES"

                    and pago.equivalente_usd

                    and pago.equivalente_usd
                        > Decimal("0.00")

                ):

                    proporcion = (

                        aplicacion
                        .monto_aplicado_usd

                        /

                        pago
                        .equivalente_usd

                    )


                    aplicado_bs = (

                        proporcion
                        *
                        pago.monto_total

                    ).quantize(

                        Decimal("0.01"),

                        rounding=(
                            ROUND_HALF_UP
                        ),

                    )


                    pagado_bs += (
                        aplicado_bs
                    )


                # ---------------------------------
                # MOVIMIENTO PARA HISTORIAL
                # ---------------------------------

                movimientos.append({

                    "aplicacion_id":
                        aplicacion.id,

                    "pago":
                        pago,

                    "pago_id":
                        pago.id,

                    "estado":
                        pago.estado,

                    "fecha_pago":
                        pago.fecha_pago,

                    "moneda":
                        pago.moneda,

                    "moneda_nombre":
                        pago.get_moneda_display(),

                    "monto_total":
                        pago.monto_total,

                    "equivalente_usd":
                        pago.equivalente_usd,

                    "monto_aplicado_usd":
                        aplicacion.monto_aplicado_usd,

                    "monto_aplicado_bs":
                        aplicado_bs,

                    "metodo":
                        pago.get_metodo_display(),

                    "referencia":
                        pago.referencia,

                    "tasa":
                        pago.tasa_bs_usd,

                    "fecha_tasa":
                        pago.fecha_tasa,

                    "fuente_tasa":
                        pago.fuente_tasa,

                    "observacion":
                        pago.observacion,

                    "aplicaciones_pago":
                        aplicaciones_del_pago,

                    "cantidad_aplicaciones":
                        len(
                            aplicaciones_del_pago
                        ),

                })


        # =====================================
        # SI NO EXISTE MENSUALIDAD
        # =====================================

        else:

            if es_futuro:

                estado_codigo = (
                    "proximo"
                )

            elif tarifa is None:

                estado_codigo = (
                    "sin_tarifa"
                )

            else:

                estado_codigo = (
                    "sin_registro"
                )


        # =====================================
        # NOMBRE DEL ESTADO
        # =====================================

        nombres_estado = {

            "al_dia":
                "Al día",

            "parcial":
                "Parcial",

            "pendiente":
                "Pendiente",

            "exonerado":
                "Exonerado",

            "sin_registro":
                "Sin registro",

            "sin_tarifa":
                "Sin tarifa",

            "proximo":
                "Próximo",

        }


        estado_nombre = (

            nombres_estado
            .get(
                estado_codigo,
                "Sin registro",
            )

        )


        # =====================================
        # CONTADORES
        # =====================================

        if estado_codigo == "al_dia":

            al_dia += 1

            meses_cubiertos += 1


        elif estado_codigo == "parcial":

            parciales += 1


        elif estado_codigo == "pendiente":

            pendientes += 1


        elif estado_codigo == "exonerado":

            exonerados += 1

            meses_cubiertos += 1


        elif estado_codigo == "sin_registro":

            sin_registro += 1


        elif estado_codigo == "sin_tarifa":

            sin_tarifa += 1


        elif estado_codigo == "proximo":

            proximos += 1


        # =====================================
        # MESES GESTIONADOS
        # =====================================

        if (

            mensualidad

            and (
                mensualidad.en_control
                or estado_codigo
                in {
                    "al_dia",
                    "parcial",
                    "pendiente",
                    "exonerado",
                }
            )

        ):

            meses_gestionados += 1


        # =====================================
        # TOTALES
        # =====================================

        total_usd += (
            pagado_usd
        )

        total_bs += (
            pagado_bs
        )


        # =====================================
        # FILA DEL MES
        # =====================================

        periodos.append({

            "mes":
                mes,

            "nombre_mes":
                nombres_meses[mes],

            "año":
                año_seleccionado,

            "mensualidad":
                mensualidad,

            "estado_codigo":
                estado_codigo,

            "estado_nombre":
                estado_nombre,

            "cuota_usd":
                cuota_usd,

            "tolerancia_usd":
                tolerancia_usd,

            "pagado_usd":
                pagado_usd,

            "pagado_bs":
                pagado_bs,

            "saldo_usd":
                saldo_usd,

            "movimientos":
                movimientos,

            "cantidad_movimientos":
                len(
                    movimientos
                ),

            "exonerado":
                (
                    mensualidad.exonerado
                    if mensualidad
                    else False
                ),

            "motivo_exoneracion":
                (
                    mensualidad
                    .motivo_exoneracion

                    if mensualidad
                    else ""
                ),

            "exonerado_en":
                (
                    mensualidad
                    .exonerado_en

                    if mensualidad
                    else None
                ),

            "exonerado_por":
                (
                    mensualidad
                    .exonerado_por

                    if mensualidad
                    else None
                ),

        })


    # =========================================
    # ESTADO GENERAL DEL AÑO
    # =========================================

    if meses_gestionados == 0:

        estado_anual_codigo = (
            "sin_gestion"
        )

        estado_anual = (
            "Sin gestión"
        )


    elif sin_tarifa > 0:

        estado_anual_codigo = (
            "revision"
        )

        estado_anual = (
            "Revisar configuración"
        )


    elif (
        pendientes > 0
        or parciales > 0
    ):

        estado_anual_codigo = (
            "pendiente"
        )

        estado_anual = (
            "Con pendientes"
        )


    else:

        estado_anual_codigo = (
            "al_dia"
        )

        estado_anual = (
            "Sin pendientes"
        )


    # =========================================
    # CONTEXTO
    # =========================================

    context = {

        "atleta":
            atleta,

        "año_seleccionado":
            año_seleccionado,

        "años_disponibles":
            años_disponibles,

        "periodos":
            periodos,

        "estado_anual":
            estado_anual,

        "estado_anual_codigo":
            estado_anual_codigo,

        "meses_gestionados":
            meses_gestionados,

        "meses_cubiertos":
            meses_cubiertos,

        "al_dia":
            al_dia,

        "parciales":
            parciales,

        "pendientes":
            pendientes,

        "exonerados":
            exonerados,

        "sin_registro":
            sin_registro,

        "sin_tarifa":
            sin_tarifa,

        "proximos":
            proximos,

        "total_pagado_usd":
            total_usd.quantize(
                Decimal("0.01")
            ),

        "total_pagado_bs":
            total_bs.quantize(
                Decimal("0.01")
            ),

        "fecha_hoy":
            hoy,

    }


    return render(
        request,
        "atletas/detalle_financiero_atleta.html",
        context,
    )

@user_passes_test(es_admin)
def administracion(request):
    """
    Panel principal de mensualidades.

    Solo crea automáticamente la mensualidad correspondiente
    al período que se está visualizando.

    Los meses históricos adicionales únicamente se crean
    cuando realmente se registra un pago para ellos.
    """

    hoy = timezone.localdate()

    mes_actual = hoy.month
    año_hoy = hoy.year

    # =========================================
    # FILTROS
    # =========================================

    try:

        año_seleccionado = int(
            request.GET.get(
                "año",
                año_hoy
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        año_seleccionado = año_hoy

    try:

        mes_filtro = int(
            request.GET.get(
                "mes",
                mes_actual
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        mes_filtro = mes_actual

    if not 1 <= mes_filtro <= 12:
        mes_filtro = mes_actual

    if not 2000 <= año_seleccionado <= 2100:
        año_seleccionado = año_hoy

    categoria_filtro = (
        request.GET
        .get(
            "categoria",
            ""
        )
        .strip()
    )

    # =========================================
    # ATLETAS
    # =========================================

    atletas = (
        Atleta.objects
        .all()
    )

    if categoria_filtro:

        atletas = atletas.filter(
            categoria=categoria_filtro
        )

    atletas = atletas.order_by(
        "apellido",
        "nombre",
        "id"
    )

    atleta_ids = list(
        atletas.values_list(
            "id",
            flat=True
        )
    )

    # =========================================
    # TARIFA DEL PERÍODO
    # =========================================

    tarifa_periodo = (
        obtener_tarifa_mensual(
            año_seleccionado,
            mes_filtro,
        )
    )

    tarifa_vigente = (
        obtener_tarifa_mensual(
            año_hoy,
            mes_actual,
        )
    )

    # =========================================
    # PREPARAR EL PERÍODO CONSULTADO
    # =========================================
    #
    # REGLAS:
    #
    # - El mes actual entra automáticamente
    #   al control para TODOS los atletas.
    #
    # - Consultar un mes histórico puede crear
    #   el registro técnico, pero NO lo convierte
    #   automáticamente en deuda.
    #
    # =========================================

    es_periodo_actual = (
        año_seleccionado == año_hoy
        and mes_filtro == mes_actual
    )

    if tarifa_periodo:

        # Para el mes actual trabajamos con todos
        # los atletas, aunque exista un filtro
        # visual por categoría.
        if es_periodo_actual:

            ids_periodo = list(
                Atleta.objects.values_list(
                    "id",
                    flat=True
                )
            )

        else:

            ids_periodo = atleta_ids


        if ids_periodo:

            existentes = set(
                Mensualidad.objects
                .filter(
                    atleta_id__in=ids_periodo,
                    año=año_seleccionado,
                    mes=mes_filtro,
                )
                .values_list(
                    "atleta_id",
                    flat=True
                )
            )


            nuevas = [

                Mensualidad(
                    atleta_id=atleta_id,
                    año=año_seleccionado,
                    mes=mes_filtro,
                    monto_pagado=Decimal("0.00"),
                    exonerado=False,
                    en_control=es_periodo_actual,
                )

                for atleta_id
                in ids_periodo

                if atleta_id
                not in existentes
            ]


            if nuevas:

                Mensualidad.objects.bulk_create(
                    nuevas,
                    ignore_conflicts=True,
                )


            # Si estamos viendo el mes actual,
            # también activamos registros técnicos
            # que ya existían por la señal.
            if es_periodo_actual:

                Mensualidad.objects.filter(
                    atleta_id__in=ids_periodo,
                    año=año_seleccionado,
                    mes=mes_filtro,
                    en_control=False,
                ).update(
                    en_control=True
                )

    # =========================================
    # TASA BCV
    # =========================================

    tasa_actual = None
    tasa_disponible = False

    try:

        tasa_actual = (
            obtener_tasa_actual()
        )

        tasa_disponible = (
            tasa_actual is not None
        )

    except TasaCambioNoDisponible:

        tasa_actual = None
        tasa_disponible = False

    # =========================================
    # PERÍODOS DISPONIBLES PARA PAGOS
    # =========================================
    #
    # Esto NO crea mensualidades antiguas.
    #
    # Solo genera las opciones que podrán
    # seleccionarse en el modal.
    # =========================================

    tarifas_por_mes = {}

    for mes in range(
        1,
        mes_filtro + 1
    ):

        tarifa = (
            obtener_tarifa_mensual(
                año_seleccionado,
                mes
            )
        )

        if tarifa:
            tarifas_por_mes[
                mes
            ] = tarifa

    meses_validos = list(
        tarifas_por_mes.keys()
    )

    # =========================================
    # MENSUALIDADES YA EXISTENTES
    # =========================================

    mensualidades_existentes = (
        Mensualidad.objects
        .filter(
            atleta_id__in=
                atleta_ids,
            año=año_seleccionado,
            mes__in=
                meses_validos,
        )
        .select_related(
            "atleta"
        )
        .prefetch_related(
            Prefetch(
                "pagos",
                queryset=(
                    PagoMensualidad.objects
                    .select_related("pago")
                ),
            )
        )
        .order_by(
            "año",
            "mes",
            "atleta_id",
        )
    )

    mapa_mensualidades = {

        (
            mensualidad.atleta_id,
            mensualidad.mes,
        ):
        mensualidad

        for mensualidad
        in mensualidades_existentes
    }

    # =========================================
    # TABLA PRINCIPAL
    # =========================================

    registros = []

    al_dia = 0
    parciales = 0
    pendientes = 0
    exonerados = 0
    sin_tarifa = 0
    sin_registro = 0

    for atleta in atletas:

        mensualidad = (
            mapa_mensualidades
            .get(
                (
                    atleta.id,
                    mes_filtro,
                )
            )
        )

        if mensualidad:

            estado_codigo = (
                mensualidad.estado_codigo
            )

            estado_nombre = (
                mensualidad.estado()
            )

            cuota_usd = (
                mensualidad.cuota_usd
            )

            total_pagado_usd = (
                mensualidad
                .total_pagado_usd
            )

            saldo_pendiente_usd = (
                mensualidad
                .saldo_pendiente_usd
            )

        elif tarifa_periodo:

            cuota_usd = (
                tarifa_periodo
                .monto_usd
            )

            total_pagado_usd = (
                Decimal("0.00")
            )

            # El período actual sí forma parte
            # del control y, si no tiene pago,
            # debe aparecer como pendiente.
            if es_periodo_actual:

                estado_codigo = (
                    "pendiente"
                )

                estado_nombre = (
                    "Pendiente"
                )

                saldo_pendiente_usd = (
                    tarifa_periodo
                    .monto_usd
                )

            # Un período histórico que nunca
            # entró al control no es una deuda.
            else:

                estado_codigo = (
                    "sin_registro"
                )

                estado_nombre = (
                    "Sin registro"
                )

                saldo_pendiente_usd = None

        else:

            estado_codigo = (
                "sin_tarifa"
            )

            estado_nombre = (
                "Sin tarifa"
            )

            cuota_usd = None

            total_pagado_usd = (
                Decimal("0.00")
            )

            saldo_pendiente_usd = None

        if estado_codigo == "al_dia":
            al_dia += 1

        elif estado_codigo == "parcial":
            parciales += 1

        elif estado_codigo == "pendiente":
            pendientes += 1

        elif estado_codigo == "exonerado":
            exonerados += 1

        elif estado_codigo == "sin_tarifa":
            sin_tarifa += 1

        elif estado_codigo == "sin_registro":
            sin_registro += 1

        # =====================================
        # MESES QUE PODRÁ PAGAR ESTE ATLETA
        # =====================================

        periodos_pago = []

        for mes in meses_validos:

            tarifa_mes = (
                tarifas_por_mes[
                    mes
                ]
            )

            mensualidad_mes = (
                mapa_mensualidades
                .get(
                    (
                        atleta.id,
                        mes,
                    )
                )
            )

            nombre_mes = (
                date_format(
                    date(
                        1900,
                        mes,
                        1
                    ),
                    "F"
                )
            )

            if mensualidad_mes:

                codigo = (
                    mensualidad_mes
                    .estado_codigo
                )

                nombre_estado = (
                    mensualidad_mes
                    .estado()
                )

                pagado = (
                    mensualidad_mes
                    .total_pagado_usd
                )


                # Un mes "Sin registro" todavía no
                # genera deuda, pero sí puede ser
                # seleccionado voluntariamente para
                # registrar un pago antiguo.
                if codigo == "sin_registro":

                    saldo = (
                        tarifa_mes
                        .monto_usd
                    )

                    seleccionable = True

                else:

                    saldo = (
                        mensualidad_mes
                        .saldo_pendiente_usd
                    )

                    seleccionable = (
                        codigo
                        in {
                            "pendiente",
                            "parcial",
                        }
                    )

            else:

                codigo = (
                    "sin_registro"
                )

                nombre_estado = (
                    "Sin registro"
                )

                pagado = (
                    Decimal("0.00")
                )

                saldo = (
                    tarifa_mes
                    .monto_usd
                )

                # Puede seleccionarse:
                # al hacerlo se creará
                # la mensualidad.
                seleccionable = True

            periodos_pago.append(
                {
                    "mes":
                        mes,

                    "año":
                        año_seleccionado,

                    "valor":
                        (
                            f"{año_seleccionado}-"
                            f"{mes:02d}"
                        ),

                    "nombre_mes":
                        nombre_mes,

                    "mensualidad":
                        mensualidad_mes,

                    "estado_codigo":
                        codigo,

                    "estado_nombre":
                        nombre_estado,

                    "cuota_usd":
                        tarifa_mes
                        .monto_usd,

                    "total_pagado_usd":
                        pagado,

                    "saldo_pendiente_usd":
                        saldo,

                    "seleccionable":
                        seleccionable,
                }
            )

        registros.append(
            {
                "atleta":
                    atleta,

                "mensualidad":
                    mensualidad,

                "estado_codigo":
                    estado_codigo,

                "estado_nombre":
                    estado_nombre,

                "cuota_usd":
                    cuota_usd,

                "total_pagado_usd":
                    total_pagado_usd,

                "saldo_pendiente_usd":
                    saldo_pendiente_usd,

                "periodos_pago":
                    periodos_pago,

                "tiene_periodos_pendientes":
                    any(
                        periodo[
                            "seleccionable"
                        ]
                        for periodo
                        in periodos_pago
                    ),
            }
        )

    total_atletas = len(
        registros
    )

    # =========================================
    # RECAUDACIÓN DEL PERÍODO
    # =========================================

    mensualidades_periodo = (
        Mensualidad.objects
        .filter(
            atleta_id__in=
                atleta_ids,
            año=año_seleccionado,
            mes=mes_filtro,
        )
    )

    total_antiguo_usd = (
        mensualidades_periodo
        .aggregate(
            total=Sum(
                "monto_pagado"
            )
        )["total"]
        or Decimal("0.00")
    )

    aplicaciones_mes = list(
        PagoMensualidad.objects
        .filter(
            mensualidad__atleta_id__in=atleta_ids,
            mensualidad__año=año_seleccionado,
            mensualidad__mes=mes_filtro,
            pago__isnull=False,
            pago__estado="activo",
        )
        .select_related(
            "pago",
            "mensualidad",
        )
    )

    total_nuevo_usd = sum(
        (
            Decimal(
                str(
                    aplicacion
                    .monto_aplicado_usd
                )
            )
            for aplicacion
            in aplicaciones_mes
        ),
        Decimal("0.00"),
    )

    total_recaudado_usd = (
        Decimal(
            str(
                total_antiguo_usd
            )
        )
        + total_nuevo_usd
    ).quantize(
        Decimal("0.01")
    )

    # =========================================
    # BOLÍVARES REALES RECIBIDOS
    # =========================================

    total_recaudado_bs = (
        Decimal("0.00")
    )

    for aplicacion in aplicaciones_mes:

        pago = aplicacion.pago

        if (
            pago
            and pago.moneda == "VES"
            and pago.equivalente_usd
            and pago.equivalente_usd
            > Decimal("0.00")
        ):

            proporcion = (
                aplicacion
                .monto_aplicado_usd
                / pago.equivalente_usd
            )

            total_recaudado_bs += (
                pago.monto_total
                * proporcion
            )

    total_recaudado_bs = (
        total_recaudado_bs
        .quantize(
            Decimal("0.01")
        )
    )

    # =========================================
    # FILTROS
    # =========================================

    meses = [

        (
            i,
            date_format(
                date(
                    1900,
                    i,
                    1
                ),
                "F"
            )
        )

        for i
        in range(
            1,
            13
        )
    ]

    categorias = (
        Atleta.objects
        .values_list(
            "categoria",
            flat=True
        )
        .distinct()
        .order_by(
            "categoria"
        )
    )

    context = {

        "registros":
            registros,

        "mes_filtro":
            mes_filtro,

        "mes_actual":
            mes_actual,

        "año_actual":
            año_seleccionado,

        "año_hoy":
            año_hoy,

        "categorias":
            categorias,

        "categoria_filtro":
            categoria_filtro,

        "meses":
            meses,

        "tarifa_periodo":
            tarifa_periodo,

        "tarifa_vigente":
            tarifa_vigente,

        "tasa_actual":
            tasa_actual,

        "tasa_disponible":
            tasa_disponible,

        "total_recaudado_usd":
            total_recaudado_usd,

        "total_recaudado_bs":
            total_recaudado_bs,

        "al_dia":
            al_dia,

        "parciales":
            parciales,

        "pendientes":
            pendientes,

        "exonerados":
            exonerados,

        "sin_tarifa":
            sin_tarifa,

        "total_atletas":
            total_atletas,

        "fecha_hoy":
            hoy,

        "sin_registro":
            sin_registro,
    }

    return render(
        request,
        "atletas/administracion.html",
        context
    )

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def lista_entrenadores(request):
    entrenadores = Entrenador.objects.all().order_by(
        "nombre",
        "apellido",
        "id"
    )

    return render(request, 'entrenadores/lista_entrenadores.html', {
        'entrenadores': entrenadores,
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

    equipos_asociados = entrenador.equipo_set.all()
    motivo_bloqueo = None

    if equipos_asociados.exists():
        motivo_bloqueo = (
            "No puedes eliminar este entrenador porque todavía tiene equipos "
            "asociados. Primero debes reasignar esos equipos a otro entrenador."
        )

    if request.method == 'POST':
        if motivo_bloqueo:
            return render(
                request,
                'entrenadores/eliminar_entrenador.html',
                {
                    'entrenador': entrenador,
                    'motivo_bloqueo': motivo_bloqueo,
                    'equipos_asociados': equipos_asociados,
                },
                status=403,
            )

        usuario = entrenador.user

        with transaction.atomic():
            entrenador.delete()
            eliminar_usuario_sin_perfil(usuario)

        messages.success(request, 'Entrenador eliminado con éxito.')
        return redirect('lista_entrenadores')

    return render(
        request,
        'entrenadores/eliminar_entrenador.html',
        {
            'entrenador': entrenador,
            'motivo_bloqueo': motivo_bloqueo,
            'equipos_asociados': equipos_asociados,
        },
    )

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
            try:
                crear_usuario_para_entrenador(
                    entrenador,
                    username,
                    password,
                    email
                )
            except IntegrityError:
                usuario_form.add_error(
                    'username',
                    'Ya existe una cuenta con este nombre de usuario.'
                )
            else:
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
    campeonatos = Campeonato.objects.all().order_by(
        '-anio',
        'nombre',
        'id'
    )

    tipo = request.GET.get('tipo', '')
    anio = request.GET.get('anio', '')

    if tipo:
        campeonatos = campeonatos.filter(tipo=tipo)

    if anio:
        campeonatos = campeonatos.filter(anio=anio)

    valores = {
        'tipo': tipo,
        'anio': anio,
    }

    return render(
        request,
        'campeonatos/lista_campeonatos.html',
        {
            'campeonatos': campeonatos,
            'valores': valores,
            'is_admin': es_admin(request.user),
            'is_entrenador': es_entrenador(request.user),
        }
    )

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
@user_passes_test(es_admin)
def eliminar_campeonato(request, campeonato_id):
    campeonato = get_object_or_404(Campeonato, id=campeonato_id)

    partidos_asociados = campeonato.partido_set.all()
    motivo_bloqueo = None

    if partidos_asociados.exists():
        motivo_bloqueo = (
            "No puedes eliminar este campeonato porque tiene partidos asociados. "
            "El historial de esos partidos debe conservarse."
        )

    if request.method == 'POST':
        if motivo_bloqueo:
            return render(
                request,
                'campeonatos/eliminar_campeonato.html',
                {
                    'campeonato': campeonato,
                    'motivo_bloqueo': motivo_bloqueo,
                    'partidos_asociados': partidos_asociados,
                },
                status=403,
            )

        campeonato.delete()
        return redirect('lista_campeonatos')

    return render(
        request,
        'campeonatos/eliminar_campeonato.html',
        {
            'campeonato': campeonato,
            'motivo_bloqueo': motivo_bloqueo,
            'partidos_asociados': partidos_asociados,
        },
    )

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def detalle_campeonato(request, campeonato_id):
    campeonato = get_object_or_404(Campeonato, id=campeonato_id)
    return render(request, 'campeonatos/detalle_campeonato.html', {
        'campeonato': campeonato
    })

def calcular_edad(nacimiento):
    hoy = timezone.localdate()
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
    equipos = (
        Equipo.objects
        .select_related('entrenador')
        .annotate(total_atletas=Count('atletas'))
        .order_by('nombre', 'id')
    )

    nombre = request.GET.get('nombre', '').strip()
    entrenador_id = request.GET.get('entrenador', '')

    if nombre:
        equipos = equipos.filter(nombre__icontains=nombre)

    if entrenador_id:
        equipos = equipos.filter(entrenador_id=entrenador_id)

    context = {
        'equipos': equipos,
        'entrenadores': Entrenador.objects.all().order_by(
            'nombre',
            'apellido',
            'id'
        ),
        'valores': {
            'nombre': nombre,
            'entrenador': entrenador_id,
        },
        'is_admin': es_admin(request.user),
        'is_entrenador': es_entrenador(request.user),
    }

    return render(
        request,
        'equipos/listar_equipos.html',
        context
    )

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

@user_passes_test(es_admin)
def eliminar_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, pk=equipo_id)

    partidos_asociados = equipo.partidos.all()
    motivo_bloqueo = None

    if partidos_asociados.exists():
        motivo_bloqueo = (
            "No puedes eliminar este equipo porque tiene partidos asociados. "
            "El historial deportivo del equipo debe conservarse."
        )

    if request.method == 'POST':
        if motivo_bloqueo:
            return render(
                request,
                'equipos/eliminar_equipo.html',
                {
                    'equipo': equipo,
                    'motivo_bloqueo': motivo_bloqueo,
                    'partidos_asociados': partidos_asociados,
                },
                status=403,
            )

        equipo.delete()
        return redirect('listar_equipos')

    return render(
        request,
        'equipos/eliminar_equipo.html',
        {
            'equipo': equipo,
            'motivo_bloqueo': motivo_bloqueo,
            'partidos_asociados': partidos_asociados,
        },
    )


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
    partidos = (
        Partido.objects
        .select_related('equipo_local', 'campeonato')
        .order_by('-fecha', '-hora', '-id')
    )

    equipo_id = request.GET.get('equipo', '').strip()
    campeonato_id = request.GET.get('campeonato', '').strip()
    estado = request.GET.get('estado', '').strip()

    if equipo_id:
        partidos = partidos.filter(equipo_local_id=equipo_id)

    if campeonato_id:
        partidos = partidos.filter(campeonato_id=campeonato_id)

    if estado:
        partidos = partidos.filter(estado=estado)

    equipos = Equipo.objects.order_by(
        'nombre',
        'id'
    )

    campeonatos = Campeonato.objects.order_by(
        '-anio',
        'nombre',
        'id'
    )

    context = {
        'partidos': partidos,
        'equipos': equipos,
        'campeonatos': campeonatos,
        'estados': Partido.ESTADOS,
        'filtros': {
            'equipo': equipo_id,
            'campeonato': campeonato_id,
            'estado': estado,
        },
        'is_admin': es_admin(request.user),
        'is_entrenador': es_entrenador(request.user),
    }

    return render(
        request,
        'partidos/lista_partidos.html',
        context
    )

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

@user_passes_test(es_admin)
def eliminar_partido(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)

    estadisticas_asociadas = partido.estadisticas.all()
    motivo_bloqueo = None

    if estadisticas_asociadas.exists():
        motivo_bloqueo = (
            "No puedes eliminar este partido porque tiene estadísticas asociadas. "
            "Primero debe conservarse o revisarse ese historial estadístico."
        )

    if request.method == 'POST':
        if motivo_bloqueo:
            return render(
                request,
                'partidos/eliminar_partido.html',
                {
                    'partido': partido,
                    'motivo_bloqueo': motivo_bloqueo,
                    'estadisticas_asociadas': estadisticas_asociadas,
                },
                status=403,
            )

        partido.delete()
        return redirect('lista_partidos')

    return render(
        request,
        'partidos/eliminar_partido.html',
        {
            'partido': partido,
            'motivo_bloqueo': motivo_bloqueo,
            'estadisticas_asociadas': estadisticas_asociadas,
        },
    )

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

    # Un atleta solo puede consultar sus propias estadísticas
    if es_atleta(request.user) and atleta.user != request.user:
        return redirect('bienvenida')

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

    meses = [(str(i), date_format(date(1900, i, 1), 'F')) for i in range(1, 13)]

    context = {
        'atleta': atleta,
        'page_obj': page_obj,
        'totales': totales,
        'es_entrenador': es_entrenador(request.user),
        'default_year': timezone.localdate().year,
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

    # Un atleta solo puede consultar su propio resumen estadístico
    if es_atleta(request.user) and atleta.user != request.user:
        return redirect('bienvenida')

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
    cedula_filtro = request.GET.get('cedula', '').strip()

    atletas_qs = (
        Estadistica.objects
        .values(
            'atleta__id',
            'atleta__nombre',
            'atleta__apellido',
            'atleta__cedula',
            'atleta__categoria'
        )
        .annotate(
            puntos=Sum('puntos'),
            saques=Sum('saques'),
            remates=Sum('remates'),
            bloqueos=Sum('bloqueos'),
            recepciones=Sum('recepciones'),
            armadas=Sum('armadas'),
            errores=Sum('errores')
        )
        .filter(
            Q(puntos__gt=0) |
            Q(saques__gt=0) |
            Q(remates__gt=0) |
            Q(bloqueos__gt=0) |
            Q(recepciones__gt=0) |
            Q(armadas__gt=0) |
            Q(errores__gt=0)
        )
    )

    if categoria_filtro:
        atletas_qs = atletas_qs.filter(
            atleta__categoria=categoria_filtro
        )

    if cedula_filtro:
        atletas_qs = atletas_qs.filter(
            atleta__cedula__icontains=cedula_filtro
        )

    atletas_qs = atletas_qs.order_by(
        'atleta__apellido',
        'atleta__nombre',
        'atleta__id'
    )

    categorias = (
        Atleta.objects
        .values_list('categoria', flat=True)
        .distinct()
        .order_by('categoria')
    )

    context = {
        'estadisticas': atletas_qs,
        'categorias': categorias,
        'valores': {
            'categoria': categoria_filtro,
            'cedula': cedula_filtro,
        },
        'is_admin': es_admin(request.user),
        'is_entrenador': es_entrenador(request.user),
    }

    return render(
        request,
        'estadisticas/estadisticas_individuales.html',
        context
    )

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
    equipo_filtrado = request.GET.get('equipo', '').strip()

    equipos = (
        Equipo.objects
        .prefetch_related('atletas')
        .order_by('nombre', 'id')
    )

    if equipo_filtrado:
        equipos = equipos.filter(id=equipo_filtrado)

    equipos_con_estadisticas = []

    for equipo in equipos:
        atletas = equipo.atletas.all()

        # Partidos donde este equipo fue el equipo local
        partidos_del_equipo = Partido.objects.filter(
            equipo_local=equipo
        )

        # Estadísticas de los atletas del equipo
        # únicamente en sus partidos
        estadisticas = Estadistica.objects.filter(
            atleta__in=atletas,
            partido__in=partidos_del_equipo
        )

        if not estadisticas.exists():
            continue

        totales = estadisticas.aggregate(
            puntos=Sum('puntos'),
            saques=Sum('saques'),
            remates=Sum('remates'),
            bloqueos=Sum('bloqueos'),
            armadas=Sum('armadas'),
            recepciones=Sum('recepciones'),
            errores=Sum('errores'),
        )

        equipos_con_estadisticas.append({
            'equipo': equipo,
            'totales': totales,
        })

    context = {
        'equipos_con_estadisticas': equipos_con_estadisticas,
        'todos_equipos': Equipo.objects.order_by(
            'nombre',
            'id'
        ),
        'equipo_filtrado': equipo_filtrado,
        'is_admin': es_admin(request.user),
        'is_entrenador': es_entrenador(request.user),
    }

    return render(
        request,
        'estadisticas/estadisticas_equipo.html',
        context
    )

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

# ============================================================
# MOTOR FINANCIERO ÚNICO PARA REPORTES
# ============================================================

_MESES_REPORTE = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}


_NOMBRES_ESTADO_REPORTE = {
    "al_dia": "Al día",
    "parcial": "Parcial",
    "pendiente": "Pendiente",
    "exonerado": "Exonerado",
    "sin_registro": "Sin registro",
    "sin_tarifa": "Sin tarifa",
    "proximo": "Próximo",
}


# Permite recibir temporalmente los valores
# utilizados por los filtros viejos del reporte.
_ALIAS_ESTADOS_REPORTE = {
    "pagado": "al_dia",
    "no_pagado": "pendiente",
    "al_dia": "al_dia",
    "parcial": "parcial",
    "pendiente": "pendiente",
    "exonerado": "exonerado",
    "sin_registro": "sin_registro",
    "sin_tarifa": "sin_tarifa",
    "proximo": "proximo",
}


def _normalizar_estado_reporte(
    estado,
):
    """
    Convierte los nombres antiguos de estados
    al sistema financiero nuevo.
    """

    estado = (
        estado
        or ""
    ).strip()


    if not estado:
        return ""


    return (
        _ALIAS_ESTADOS_REPORTE
        .get(
            estado,
            "",
        )
    )



def _construir_reporte_financiero(
    *,
    año,
    mes_inicio=1,
    mes_fin=12,
    categoria="",
    nombre="",
    cedula="",
    estado_filtro="",
):
    """
    Construye toda la información financiera
    utilizada por:

    - reporte web;
    - Excel;
    - PDF.

    Esta función NO modifica la base de datos.

    Los estados y saldos utilizan exactamente
    la misma lógica financiera de Mensualidad.
    """

    hoy = timezone.localdate()


    # ========================================================
    # VALIDAR AÑO
    # ========================================================

    try:

        año = int(
            año
        )

    except (
        TypeError,
        ValueError,
    ):

        año = hoy.year


    if not (
        2000
        <= año
        <= 2100
    ):

        año = hoy.year



    # ========================================================
    # VALIDAR RANGO DE MESES
    # ========================================================

    try:

        mes_inicio = int(
            mes_inicio
        )

    except (
        TypeError,
        ValueError,
    ):

        mes_inicio = 1


    try:

        mes_fin = int(
            mes_fin
        )

    except (
        TypeError,
        ValueError,
    ):

        mes_fin = 12


    mes_inicio = max(
        1,
        min(
            mes_inicio,
            12,
        ),
    )


    mes_fin = max(
        1,
        min(
            mes_fin,
            12,
        ),
    )


    if mes_inicio > mes_fin:

        mes_inicio, mes_fin = (
            mes_fin,
            mes_inicio,
        )



    # ========================================================
    # NORMALIZAR FILTROS
    # ========================================================

    categoria = (
        categoria
        or ""
    ).strip()


    nombre = (
        nombre
        or ""
    ).strip()


    cedula = (
        cedula
        or ""
    ).strip()


    estado_filtro = (
        _normalizar_estado_reporte(
            estado_filtro
        )
    )



    # ========================================================
    # ATLETAS
    # ========================================================

    atletas_qs = (
        Atleta.objects
        .all()
    )


    if categoria:

        atletas_qs = (
            atletas_qs
            .filter(
                categoria=categoria
            )
        )


    if nombre:

        atletas_qs = (
            atletas_qs
            .filter(
                Q(
                    nombre__icontains=nombre
                )
                |
                Q(
                    apellido__icontains=nombre
                )
            )
        )


    if cedula:

        atletas_qs = (
            atletas_qs
            .filter(
                cedula__icontains=cedula
            )
        )


    atletas = list(

        atletas_qs
        .order_by(
            "apellido",
            "nombre",
            "id",
        )

    )


    atleta_ids = [

        atleta.id

        for atleta
        in atletas

    ]



    # ========================================================
    # APLICACIONES DE PAGO
    # ========================================================

    aplicaciones_qs = (

        PagoMensualidad.objects
        .select_related(
            "pago"
        )
        .order_by(
            "pago__fecha_pago",
            "pago__creado_en",
            "id",
        )

    )



    # ========================================================
    # MENSUALIDADES
    #
    # Se cargan todas de una sola vez para evitar
    # hacer una consulta por atleta y por mes.
    # ========================================================

    if atleta_ids:

        mensualidades = (

            Mensualidad.objects
            .filter(
                atleta_id__in=atleta_ids,
                año=año,
                mes__gte=mes_inicio,
                mes__lte=mes_fin,
            )
            .prefetch_related(

                Prefetch(
                    "pagos",
                    queryset=aplicaciones_qs,
                )

            )

        )

    else:

        mensualidades = (
            Mensualidad.objects.none()
        )


    mensualidades_por_clave = {

        (
            mensualidad.atleta_id,
            mensualidad.mes,
        ):
            mensualidad

        for mensualidad
        in mensualidades

    }



    # ========================================================
    # TARIFAS DEL RANGO
    #
    # Se resuelven una sola vez por mes.
    # ========================================================

    tarifas_por_mes = {

        mes:
            obtener_tarifa_mensual(
                año,
                mes,
            )

        for mes
        in range(
            mes_inicio,
            mes_fin + 1,
        )

    }



    # ========================================================
    # DEFINICIÓN DE MESES
    # ========================================================

    meses = [

        {
            "numero":
                mes,

            "nombre":
                _MESES_REPORTE[mes],

            "abreviatura":
                _MESES_REPORTE[mes][:3],
        }

        for mes
        in range(
            mes_inicio,
            mes_fin + 1,
        )

    ]



    # ========================================================
    # RESULTADO
    # ========================================================

    filas = []


    # Totales globales.
    total_pagado_usd = Decimal(
        "0.0000"
    )

    total_pagado_bs = Decimal(
        "0.00"
    )

    total_pendiente_usd = Decimal(
        "0.00"
    )


    total_meses_gestionados = 0
    total_meses_cubiertos = 0


    conteo_estados = {

        "al_dia": 0,
        "parcial": 0,
        "pendiente": 0,
        "exonerado": 0,
        "sin_registro": 0,
        "sin_tarifa": 0,
        "proximo": 0,

    }



    # ========================================================
    # RECORRER ATLETAS
    # ========================================================

    for atleta in atletas:


        periodos = []


        atleta_pagado_usd = Decimal(
            "0.0000"
        )

        atleta_pagado_bs = Decimal(
            "0.00"
        )

        atleta_pendiente_usd = Decimal(
            "0.00"
        )


        atleta_meses_gestionados = 0
        atleta_meses_cubiertos = 0


        estados_atleta = {

            "al_dia": 0,
            "parcial": 0,
            "pendiente": 0,
            "exonerado": 0,
            "sin_registro": 0,
            "sin_tarifa": 0,
            "proximo": 0,

        }



        # ====================================================
        # MESES DEL ATLETA
        # ====================================================

        for mes in range(
            mes_inicio,
            mes_fin + 1,
        ):


            mensualidad = (
                mensualidades_por_clave
                .get(
                    (
                        atleta.id,
                        mes,
                    )
                )
            )


            tarifa = (
                tarifas_por_mes
                .get(
                    mes
                )
            )


            es_futuro = (

                (
                    año,
                    mes,
                )

                >

                (
                    hoy.year,
                    hoy.month,
                )

            )



            # ================================================
            # DATOS INICIALES
            # ================================================

            cuota_usd = (

                Decimal(
                    str(
                        tarifa.monto_usd
                    )
                )

                if tarifa
                else None

            )


            tolerancia_usd = (

                Decimal(
                    str(
                        tarifa.tolerancia_usd
                    )
                )

                if tarifa
                else None

            )


            pagado_usd = Decimal(
                "0.0000"
            )


            pagado_bs = Decimal(
                "0.00"
            )


            saldo_usd = None


            en_control = False


            exonerado = False



            # ================================================
            # EXISTE MENSUALIDAD
            # ================================================

            if mensualidad:


                en_control = bool(
                    mensualidad.en_control
                )


                exonerado = bool(
                    mensualidad.exonerado
                )


                pagado_usd = (

                    mensualidad
                    .total_pagado_usd

                )


                estado_codigo = (

                    mensualidad
                    .estado_codigo

                )



                # --------------------------------------------
                # FUTURO NO GESTIONADO
                # --------------------------------------------

                if (

                    es_futuro

                    and not mensualidad.en_control

                    and not mensualidad.exonerado

                    and pagado_usd
                        <= Decimal("0.00")

                ):

                    estado_codigo = (
                        "proximo"
                    )



                # --------------------------------------------
                # SALDO
                # --------------------------------------------

                if estado_codigo not in {
                    "sin_registro",
                    "proximo",
                }:

                    saldo_usd = (

                        mensualidad
                        .saldo_pendiente_usd

                    )



                # --------------------------------------------
                # BOLÍVARES APLICADOS AL MES
                # --------------------------------------------

                for aplicacion in (
                    mensualidad
                    .pagos
                    .all()
                ):


                    pago = (
                        aplicacion.pago
                    )


                    if not pago:

                        continue


                    if (
                        pago.estado
                        != "activo"
                    ):

                        continue


                    if (
                        pago.moneda
                        != "VES"
                    ):

                        continue


                    if (
                        not pago.equivalente_usd

                        or pago.equivalente_usd
                            <= Decimal("0.00")
                    ):

                        continue


                    proporcion = (

                        aplicacion
                        .monto_aplicado_usd

                        /

                        pago.equivalente_usd

                    )


                    aplicado_bs = (

                        proporcion
                        *
                        pago.monto_total

                    ).quantize(

                        Decimal("0.01"),

                        rounding=(
                            ROUND_HALF_UP
                        ),

                    )


                    pagado_bs += (
                        aplicado_bs
                    )



            # ================================================
            # NO EXISTE MENSUALIDAD
            # ================================================

            else:


                if es_futuro:

                    estado_codigo = (
                        "proximo"
                    )


                elif tarifa is None:

                    estado_codigo = (
                        "sin_tarifa"
                    )


                else:

                    estado_codigo = (
                        "sin_registro"
                    )



            # ================================================
            # NOMBRE DEL ESTADO
            # ================================================

            estado_nombre = (

                _NOMBRES_ESTADO_REPORTE
                .get(
                    estado_codigo,
                    "Sin registro",
                )

            )



            # ================================================
            # MES GESTIONADO
            # ================================================

            gestionado = bool(

                mensualidad

                and (

                    mensualidad.en_control

                    or estado_codigo in {
                        "al_dia",
                        "parcial",
                        "pendiente",
                        "exonerado",
                    }

                )

            )



            # ================================================
            # MES CUBIERTO
            # ================================================

            cubierto = (

                estado_codigo
                in {
                    "al_dia",
                    "exonerado",
                }

            )



            # ================================================
            # ACUMULAR ATLETA
            # ================================================

            atleta_pagado_usd += (
                pagado_usd
            )


            atleta_pagado_bs += (
                pagado_bs
            )


            if (
                saldo_usd is not None

                and saldo_usd
                    > Decimal("0.00")
            ):

                atleta_pendiente_usd += (
                    saldo_usd
                )


            if gestionado:

                atleta_meses_gestionados += 1


            if cubierto:

                atleta_meses_cubiertos += 1


            if (
                estado_codigo
                in estados_atleta
            ):

                estados_atleta[
                    estado_codigo
                ] += 1



            # ================================================
            # FILA DEL MES
            # ================================================

            periodos.append({

                "mes":
                    mes,

                "nombre_mes":
                    _MESES_REPORTE[
                        mes
                    ],

                "abreviatura":
                    _MESES_REPORTE[
                        mes
                    ][:3],

                "año":
                    año,

                "mensualidad":
                    mensualidad,

                "estado_codigo":
                    estado_codigo,

                "estado_nombre":
                    estado_nombre,

                "cuota_usd":
                    cuota_usd,

                "tolerancia_usd":
                    tolerancia_usd,

                "pagado_usd":
                    pagado_usd.quantize(
                        Decimal("0.01")
                    ),

                "pagado_bs":
                    pagado_bs.quantize(
                        Decimal("0.01")
                    ),

                "saldo_usd":
                    (
                        saldo_usd.quantize(
                            Decimal("0.01")
                        )
                        if saldo_usd is not None
                        else None
                    ),

                "en_control":
                    en_control,

                "exonerado":
                    exonerado,

                "gestionado":
                    gestionado,

                "cubierto":
                    cubierto,

            })



        # ====================================================
        # FILTRO DE ESTADO
        #
        # El atleta aparece si al menos uno de los meses
        # seleccionados tiene el estado buscado.
        # ====================================================

        if estado_filtro:

            coincide_estado = any(

                periodo[
                    "estado_codigo"
                ]
                == estado_filtro

                for periodo
                in periodos

            )


            if not coincide_estado:

                continue



        # ====================================================
        # AGREGAR ATLETA AL REPORTE
        # ====================================================

        fila = {

            "id":
                atleta.id,

            "atleta":
                atleta,

            "nombre":
                atleta.nombre,

            "apellido":
                atleta.apellido,

            "nombre_completo":
                (
                    f"{atleta.nombre} "
                    f"{atleta.apellido}"
                ).strip(),

            "cedula":
                atleta.cedula,

            "categoria":
                atleta.categoria,

            "periodos":
                periodos,

            # Compatibilidad temporal con
            # algunas partes del reporte viejo.
            "pagos":
                periodos,

            "total_pagado_usd":
                atleta_pagado_usd.quantize(
                    Decimal("0.01")
                ),

            "total_pagado_bs":
                atleta_pagado_bs.quantize(
                    Decimal("0.01")
                ),

            "total_pendiente_usd":
                atleta_pendiente_usd.quantize(
                    Decimal("0.01")
                ),

            "meses_gestionados":
                atleta_meses_gestionados,

            "meses_cubiertos":
                atleta_meses_cubiertos,

            "estados":
                estados_atleta,

        }


        filas.append(
            fila
        )



        # ====================================================
        # TOTALES GENERALES
        # ====================================================

        total_pagado_usd += (
            atleta_pagado_usd
        )


        total_pagado_bs += (
            atleta_pagado_bs
        )


        total_pendiente_usd += (
            atleta_pendiente_usd
        )


        total_meses_gestionados += (
            atleta_meses_gestionados
        )


        total_meses_cubiertos += (
            atleta_meses_cubiertos
        )


        for (
            codigo,
            cantidad,
        ) in estados_atleta.items():

            conteo_estados[
                codigo
            ] += cantidad



    # ========================================================
    # RESULTADO FINAL
    # ========================================================

    return {

        "año":
            año,

        "mes_inicio":
            mes_inicio,

        "mes_fin":
            mes_fin,

        "meses":
            meses,

        "filas":
            filas,

        "total_atletas":
            len(
                filas
            ),

        "totales": {

            "pagado_usd":
                total_pagado_usd.quantize(
                    Decimal("0.01")
                ),

            "pagado_bs":
                total_pagado_bs.quantize(
                    Decimal("0.01")
                ),

            "pendiente_usd":
                total_pendiente_usd.quantize(
                    Decimal("0.01")
                ),

            "meses_gestionados":
                total_meses_gestionados,

            "meses_cubiertos":
                total_meses_cubiertos,

            "estados":
                conteo_estados,

        },

        "filtros": {

            "categoria":
                categoria,

            "nombre":
                nombre,

            "cedula":
                cedula,

            "estado":
                estado_filtro,

        },

    }

@user_passes_test(es_admin)
def reporte_pagos_view(request):
    """
    Reporte general de mensualidades.

    Toda la lógica financiera proviene de
    _construir_reporte_financiero().
    """

    hoy = timezone.localdate()

    # ========================================================
    # FILTROS
    # ========================================================

    año = request.GET.get("año") or hoy.year
    mes_inicio = request.GET.get("mes_inicio") or 1
    mes_fin = request.GET.get("mes_fin") or 12

    categoria = request.GET.get("categoria", "").strip()
    nombre = request.GET.get("nombre", "").strip()
    cedula = request.GET.get("cedula", "").strip()
    estado_filtro = request.GET.get("estado", "").strip()

    # ========================================================
    # FILAS POR PÁGINA
    # ========================================================

    try:
        por_pagina = int(
            request.GET.get(
                "por_pagina",
                15,
            )
        )
    except (TypeError, ValueError):
        por_pagina = 15

    if por_pagina not in {15, 20, 50}:
        por_pagina = 15

    # ========================================================
    # MOTOR FINANCIERO
    # ========================================================

    reporte = _construir_reporte_financiero(
        año=año,
        mes_inicio=mes_inicio,
        mes_fin=mes_fin,
        categoria=categoria,
        nombre=nombre,
        cedula=cedula,
        estado_filtro=estado_filtro,
    )

    año_seleccionado = reporte["año"]
    mes_inicio = reporte["mes_inicio"]
    mes_fin = reporte["mes_fin"]
    estado_filtro = reporte["filtros"]["estado"]

    # ========================================================
    # PAGINACIÓN
    # ========================================================


    paginator = Paginator(
        reporte["filas"],
        por_pagina,
    )

    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # ========================================================
    # PAGINACIÓN NUMÉRICA DESLIZANTE
    #
    # Se muestran como máximo 5 números.
    #
    # Ejemplos:
    #
    # Página 1:
    # 1 2 3 4 5
    #
    # Página 4:
    # 2 3 4 5 6
    #
    # Página 8:
    # 6 7 8 9 10
    #
    # Cerca del final:
    # 16 17 18 19 20
    # ========================================================

    total_paginas = paginator.num_pages
    pagina_actual = page_obj.number

    cantidad_paginas_visibles = 5


    if total_paginas <= cantidad_paginas_visibles:

        pagina_inicio = 1
        pagina_fin = total_paginas

    else:

        pagina_inicio = pagina_actual - 2
        pagina_fin = pagina_actual + 2


        # Cerca del inicio
        if pagina_inicio < 1:

            pagina_inicio = 1
            pagina_fin = cantidad_paginas_visibles


        # Cerca del final
        if pagina_fin > total_paginas:

            pagina_fin = total_paginas

            pagina_inicio = (
                total_paginas
                - cantidad_paginas_visibles
                + 1
            )


    paginas_paginacion = list(
        range(
            pagina_inicio,
            pagina_fin + 1,
        )
    )

    # ========================================================
    # QUERYSTRING SIN PAGE
    # ========================================================

    parametros_paginacion = request.GET.copy()
    parametros_paginacion.pop("page", None)
    querystring_sin_page = parametros_paginacion.urlencode()

    # ========================================================
    # CATEGORÍAS
    # ========================================================

    categorias = list(
        Atleta.objects
        .exclude(categoria__isnull=True)
        .exclude(categoria="")
        .values_list("categoria", flat=True)
        .distinct()
        .order_by("categoria")
    )

    # ========================================================
    # AÑOS DISPONIBLES
    # ========================================================

    años_disponibles = set(
        Mensualidad.objects
        .values_list("año", flat=True)
        .distinct()
    )

    años_disponibles.add(hoy.year)
    años_disponibles.add(año_seleccionado)

    años_disponibles = sorted(
        años_disponibles,
        reverse=True,
    )

    # ========================================================
    # SELECTORES
    # ========================================================

    meses_selector = [
        (mes, _MESES_REPORTE[mes])
        for mes in range(1, 13)
    ]

    estados_disponibles = [
        ("al_dia", "Al día"),
        ("parcial", "Parcial"),
        ("pendiente", "Pendiente"),
        ("exonerado", "Exonerado"),
        ("sin_registro", "Sin registro"),
        ("proximo", "Próximo"),
        ("sin_tarifa", "Sin tarifa"),
    ]

    # ========================================================
    # CONTEXTO
    # ========================================================

    context = {
        "resumen": page_obj,
        "page_obj": page_obj,
        "reporte": reporte,
        "totales": reporte["totales"],
        "meses": reporte["meses"],

        "año_actual": hoy.year,
        "año_seleccionado": año_seleccionado,
        "años_disponibles": años_disponibles,
        "mes_inicio": mes_inicio,
        "mes_fin": mes_fin,
        "categoria_seleccionada": reporte["filtros"]["categoria"],
        "nombre": reporte["filtros"]["nombre"],
        "cedula": reporte["filtros"]["cedula"],
        "estado": estado_filtro,

        "categorias": categorias,
        "meses_selector": meses_selector,
        "estados_disponibles": estados_disponibles,

        "por_pagina": por_pagina,
        "paginas_paginacion": paginas_paginacion,
        "querystring_sin_page": querystring_sin_page,
    }

    return render(
        request,
        "reportes/reporte_pagos.html",
        context,
    )

@user_passes_test(es_admin)
def exportar_pagos_excel(request):
    """
    Exporta el reporte de mensualidades a Excel.

    Utiliza el mismo motor financiero que
    el reporte web.

    Respeta:
    - tarifas históricas;
    - pagos activos;
    - pagos anulados;
    - pagos parciales;
    - exoneraciones;
    - sin registro;
    - períodos próximos;
    - filtros aplicados.
    """

    import io
    import os

    from django.conf import settings
    from django.http import HttpResponse

    from openpyxl import Workbook

    from openpyxl.drawing.image import (
        Image as XLImage,
    )

    from openpyxl.styles import (
        Alignment,
        Border,
        Font,
        PatternFill,
        Side,
    )

    from openpyxl.utils import (
        get_column_letter,
    )


    # ========================================================
    # FILTROS
    # ========================================================

    hoy = timezone.localdate()


    año = (
        request.GET.get("año")
        or hoy.year
    )


    mes_inicio = (
        request.GET.get("mes_inicio")
        or 1
    )


    mes_fin = (
        request.GET.get("mes_fin")
        or 12
    )


    categoria = (
        request.GET
        .get(
            "categoria",
            "",
        )
        .strip()
    )


    nombre = (
        request.GET
        .get(
            "nombre",
            "",
        )
        .strip()
    )


    cedula = (
        request.GET
        .get(
            "cedula",
            "",
        )
        .strip()
    )


    estado = (
        request.GET
        .get(
            "estado",
            "",
        )
        .strip()
    )


    # ========================================================
    # MOTOR FINANCIERO
    # ========================================================

    reporte = (
        _construir_reporte_financiero(
            año=año,
            mes_inicio=mes_inicio,
            mes_fin=mes_fin,
            categoria=categoria,
            nombre=nombre,
            cedula=cedula,
            estado_filtro=estado,
        )
    )


    año = reporte["año"]

    mes_inicio = reporte["mes_inicio"]

    mes_fin = reporte["mes_fin"]

    filas = reporte["filas"]

    meses = reporte["meses"]

    totales = reporte["totales"]


    # ========================================================
    # CREAR LIBRO
    # ========================================================

    wb = Workbook()

    ws = wb.active

    ws.title = "Mensualidades"

    ws.sheet_view.showGridLines = False


    # ========================================================
    # COLUMNAS
    # ========================================================

    encabezados = [
        "Atleta",
        "Cédula",
        "Categoría",
    ]


    for mes in meses:

        encabezados.append(
            mes["nombre"]
        )


    encabezados += [
        "Pagado Bs",
        "Pagado USD",
        "Pendiente USD",
        "Cubiertos",
    ]


    total_columnas = len(
        encabezados
    )


    ultima_columna = (
        get_column_letter(
            total_columnas
        )
    )


    # Se mantiene un ancho visual mínimo
    # para que la cabecera no quede corta
    # si se exportan pocos meses.

    total_columnas_visual = max(
        total_columnas,
        10,
    )


    ultima_columna_visual = (
        get_column_letter(
            total_columnas_visual
        )
    )


    # ========================================================
    # COLORES
    # ========================================================

    azul_oscuro = "2A73B6"

    azul_olympo = "158EFF"

    negro = "212529"

    blanco = "FFFFFF"

    gris_claro = "F8F9FA"

    gris_borde = "DEE2E6"


    color_al_dia = "D1E7DD"

    color_parcial = "FFF3CD"

    color_pendiente = "F8D7DA"

    color_exonerado = "CFF4FC"

    color_sin_registro = "E2E3E5"

    color_proximo = "F8F9FA"

    color_sin_tarifa = "343A40"


    borde_fino = Side(
        style="thin",
        color=gris_borde,
    )


    borde_celda = Border(
        left=borde_fino,
        right=borde_fino,
        top=borde_fino,
        bottom=borde_fino,
    )


    # ========================================================
    # CABECERA AZUL
    # ========================================================

    for fila_excel in range(
        1,
        3,
    ):

        for columna_excel in range(
            1,
            total_columnas_visual + 1,
        ):

            celda = ws.cell(
                row=fila_excel,
                column=columna_excel,
            )


            # Simulación del degradado OLYMPO
            # utilizando los dos tonos principales.

            if (
                columna_excel
                <= total_columnas_visual // 2
            ):

                color = azul_oscuro

            else:

                color = azul_olympo


            celda.fill = PatternFill(
                fill_type="solid",
                fgColor=color,
            )


    # ========================================================
    # LOGO
    # ========================================================

    logo_path = os.path.join(
        settings.BASE_DIR,
        "static",
        "img",
        "logo-olympo.jpeg",
    )


    if os.path.exists(
        logo_path
    ):

        try:

            logo = XLImage(
                logo_path
            )


            # Logo aumentado

            logo.width = 90

            logo.height = 90


            ws.add_image(
                logo,
                "A1",
            )


        except Exception:

            # El reporte debe seguir
            # generándose aunque el logo
            # presente algún problema.

            pass


    # ========================================================
    # TÍTULO
    # ========================================================

    ws.merge_cells(
        start_row=1,
        start_column=3,
        end_row=1,
        end_column=total_columnas_visual,
    )


    ws.merge_cells(
        start_row=2,
        start_column=3,
        end_row=2,
        end_column=total_columnas_visual,
    )


    ws["C1"] = (
        "Escuela Deportiva OLYMPO"
    )


    ws["C2"] = (
        f"Reporte de mensualidades · "
        f"{_MESES_REPORTE[mes_inicio]} "
        f"a {_MESES_REPORTE[mes_fin]} "
        f"{año}"
    )


    ws["C1"].font = Font(
        size=16,
        bold=True,
        color=blanco,
    )


    ws["C2"].font = Font(
        size=11,
        bold=True,
        color=blanco,
    )


    ws["C1"].alignment = Alignment(
        vertical="center",
    )


    ws["C2"].alignment = Alignment(
        vertical="center",
    )


    # Más espacio para el logo grande

    ws.row_dimensions[1].height = 42

    ws.row_dimensions[2].height = 38


    # ========================================================
    # FILTROS UTILIZADOS
    # ========================================================

    filtros_texto = []


    if categoria:

        filtros_texto.append(
            f"Categoría: {categoria}"
        )


    if nombre:

        filtros_texto.append(
            f"Nombre: {nombre}"
        )


    if cedula:

        filtros_texto.append(
            f"Cédula: {cedula}"
        )


    if reporte["filtros"]["estado"]:

        nombre_estado = (
            _NOMBRES_ESTADO_REPORTE
            .get(
                reporte["filtros"]["estado"],
                reporte["filtros"]["estado"],
            )
        )


        filtros_texto.append(
            f"Estado: {nombre_estado}"
        )


    if filtros_texto:

        texto_filtros = (
            "Filtros: "
            +
            " · ".join(
                filtros_texto
            )
        )

    else:

        texto_filtros = (
            "Filtros: todos los atletas"
        )


    ws.merge_cells(
        f"A3:{ultima_columna_visual}3"
    )


    ws["A3"] = texto_filtros


    ws["A3"].font = Font(
        italic=True,
        color="5F6B76",
        size=9,
    )


    ws["A3"].alignment = Alignment(
        vertical="center",
    )


    ws.row_dimensions[3].height = 22


    # ========================================================
    # RESUMEN GENERAL
    # ========================================================

    resumen = [
        (
            "Atletas",
            reporte["total_atletas"],
        ),

        (
            "Recaudado Bs",
            float(
                totales["pagado_bs"]
            ),
        ),

        (
            "Equiv. USD",
            float(
                totales["pagado_usd"]
            ),
        ),

        (
            "Pendiente USD",
            float(
                totales["pendiente_usd"]
            ),
        ),

        (
            "Cubiertos / Gestionados",
            (
                f"{totales['meses_cubiertos']}"
                f" / "
                f"{totales['meses_gestionados']}"
            ),
        ),
    ]


    columna_resumen = 1


    for (
        etiqueta,
        valor,
    ) in resumen:

        celda_etiqueta = (
            ws.cell(
                row=5,
                column=columna_resumen,
            )
        )


        celda_valor = (
            ws.cell(
                row=5,
                column=columna_resumen + 1,
            )
        )


        celda_etiqueta.value = (
            etiqueta
        )


        celda_valor.value = (
            valor
        )


        celda_etiqueta.fill = (
            PatternFill(
                fill_type="solid",
                fgColor="EAF3FB",
            )
        )


        celda_valor.fill = (
            PatternFill(
                fill_type="solid",
                fgColor="FFFFFF",
            )
        )


        celda_etiqueta.font = Font(
            bold=True,
            color=azul_oscuro,
            size=9,
        )


        celda_valor.font = Font(
            bold=True,
            color=negro,
            size=10,
        )


        celda_etiqueta.alignment = (
            Alignment(
                horizontal="center",
                vertical="center",
                wrap_text=True,
            )
        )


        celda_valor.alignment = (
            Alignment(
                horizontal="center",
                vertical="center",
                wrap_text=True,
            )
        )


        celda_etiqueta.border = (
            borde_celda
        )


        celda_valor.border = (
            borde_celda
        )


        columna_resumen += 2


    # ========================================================
    # FORMATOS MONETARIOS DEL RESUMEN
    # ========================================================

    ws["D5"].number_format = (
        '#,##0.00'
    )


    ws["F5"].number_format = (
        '$#,##0.00'
    )


    ws["H5"].number_format = (
        '$#,##0.00'
    )


    ws.row_dimensions[5].height = 35


    # ========================================================
    # CONTEO DE ESTADOS
    # ========================================================

    estados_texto = (
        f"Al día: "
        f"{totales['estados']['al_dia']}"
        f"   |   Parcial: "
        f"{totales['estados']['parcial']}"
        f"   |   Pendiente: "
        f"{totales['estados']['pendiente']}"
        f"   |   Exonerado: "
        f"{totales['estados']['exonerado']}"
        f"   |   Sin registro: "
        f"{totales['estados']['sin_registro']}"
        f"   |   Próximo: "
        f"{totales['estados']['proximo']}"
        f"   |   Sin tarifa: "
        f"{totales['estados']['sin_tarifa']}"
    )


    ws.merge_cells(
        f"A6:{ultima_columna_visual}6"
    )


    ws["A6"] = (
        estados_texto
    )


    ws["A6"].fill = PatternFill(
        fill_type="solid",
        fgColor=gris_claro,
    )


    ws["A6"].font = Font(
        size=9,
        color="495057",
    )


    ws["A6"].alignment = (
        Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True,
        )
    )


    ws.row_dimensions[6].height = 25


    # ========================================================
    # TABLA
    # ========================================================

    fila_encabezado = 8

    fila_datos_inicio = 9


    for (
        numero_columna,
        encabezado,
    ) in enumerate(
        encabezados,
        start=1,
    ):

        celda = ws.cell(
            row=fila_encabezado,
            column=numero_columna,
        )


        celda.value = (
            encabezado
        )


        celda.fill = PatternFill(
            fill_type="solid",
            fgColor=negro,
        )


        celda.font = Font(
            bold=True,
            color=blanco,
            size=9,
        )


        celda.alignment = (
            Alignment(
                horizontal="center",
                vertical="center",
                wrap_text=True,
            )
        )


        celda.border = (
            borde_celda
        )


    ws.row_dimensions[
        fila_encabezado
    ].height = 30


    # ========================================================
    # COLORES POR ESTADO
    # ========================================================

    mapa_fill_estado = {

        "al_dia":
            color_al_dia,

        "parcial":
            color_parcial,

        "pendiente":
            color_pendiente,

        "exonerado":
            color_exonerado,

        "sin_registro":
            color_sin_registro,

        "proximo":
            color_proximo,

        "sin_tarifa":
            color_sin_tarifa,

    }


    # ========================================================
    # FILAS DE ATLETAS
    # ========================================================

    fila_excel = (
        fila_datos_inicio
    )


    for fila in filas:


        # ----------------------------------------
        # DATOS PERSONALES
        # ----------------------------------------

        valores_iniciales = [

            fila[
                "nombre_completo"
            ],

            fila[
                "cedula"
            ] or "",

            fila[
                "categoria"
            ] or "",

        ]


        for (
            numero_columna,
            valor,
        ) in enumerate(
            valores_iniciales,
            start=1,
        ):

            celda = ws.cell(
                row=fila_excel,
                column=numero_columna,
            )


            celda.value = (
                valor
            )


            celda.alignment = (
                Alignment(
                    horizontal=(
                        "left"
                        if numero_columna == 1
                        else "center"
                    ),
                    vertical="center",
                    wrap_text=True,
                )
            )


            celda.border = (
                borde_celda
            )


        # ----------------------------------------
        # MESES
        # ----------------------------------------

        columna_mes = 4


        for periodo in fila[
            "periodos"
        ]:

            codigo = (
                periodo[
                    "estado_codigo"
                ]
            )


            if codigo == "al_dia":

                valor_mes = (
                    "Al día\n"
                    f"${periodo['pagado_usd']:.2f}"
                )


            elif codigo == "parcial":

                valor_mes = (
                    "Parcial\n"
                    f"${periodo['pagado_usd']:.2f}"
                    f" / "
                    f"${periodo['cuota_usd']:.2f}"
                )


            elif codigo == "pendiente":

                valor_mes = (
                    "Pendiente\n"
                    f"Saldo "
                    f"${periodo['saldo_usd']:.2f}"
                )


            elif codigo == "exonerado":

                valor_mes = (
                    "Exonerado"
                )


            elif codigo == "sin_registro":

                valor_mes = (
                    "Sin registro"
                )


            elif codigo == "proximo":

                valor_mes = (
                    "Próximo"
                )


            else:

                valor_mes = (
                    "Sin tarifa"
                )


            celda = ws.cell(
                row=fila_excel,
                column=columna_mes,
            )


            celda.value = (
                valor_mes
            )


            celda.fill = (
                PatternFill(
                    fill_type="solid",
                    fgColor=(
                        mapa_fill_estado[
                            codigo
                        ]
                    ),
                )
            )


            celda.font = Font(
                size=8,
                bold=True,
                color=(
                    blanco
                    if codigo
                    == "sin_tarifa"
                    else negro
                ),
            )


            celda.alignment = (
                Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True,
                )
            )


            celda.border = (
                borde_celda
            )


            columna_mes += 1


        # ----------------------------------------
        # TOTALES
        # ----------------------------------------

        columna_pagado_bs = (
            4
            +
            len(
                fila[
                    "periodos"
                ]
            )
        )


        columna_pagado_usd = (
            columna_pagado_bs + 1
        )


        columna_pendiente = (
            columna_pagado_bs + 2
        )


        columna_cubiertos = (
            columna_pagado_bs + 3
        )


        # Bs

        celda_bs = ws.cell(
            row=fila_excel,
            column=columna_pagado_bs,
        )


        celda_bs.value = float(
            fila[
                "total_pagado_bs"
            ]
        )


        celda_bs.number_format = (
            '#,##0.00'
        )


        # USD

        celda_usd = ws.cell(
            row=fila_excel,
            column=columna_pagado_usd,
        )


        celda_usd.value = float(
            fila[
                "total_pagado_usd"
            ]
        )


        celda_usd.number_format = (
            '$#,##0.00'
        )


        # Pendiente

        celda_pendiente = ws.cell(
            row=fila_excel,
            column=columna_pendiente,
        )


        celda_pendiente.value = float(
            fila[
                "total_pendiente_usd"
            ]
        )


        celda_pendiente.number_format = (
            '$#,##0.00'
        )


        # Cubiertos

        celda_cubiertos = ws.cell(
            row=fila_excel,
            column=columna_cubiertos,
        )


        celda_cubiertos.value = (
            f"{fila['meses_cubiertos']}"
            f" / "
            f"{fila['meses_gestionados']}"
        )


        # Estilos

        for columna in range(
            columna_pagado_bs,
            columna_cubiertos + 1,
        ):

            celda = ws.cell(
                row=fila_excel,
                column=columna,
            )


            celda.alignment = (
                Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True,
                )
            )


            celda.border = (
                borde_celda
            )


        celda_bs.font = Font(
            color="198754",
            bold=True,
            size=8,
        )


        celda_usd.font = Font(
            color="0D6EFD",
            bold=True,
            size=8,
        )


        if (
            fila[
                "total_pendiente_usd"
            ]
            > 0
        ):

            celda_pendiente.font = (
                Font(
                    color="DC3545",
                    bold=True,
                    size=8,
                )
            )

        else:

            celda_pendiente.font = (
                Font(
                    color="198754",
                    bold=True,
                    size=8,
                )
            )


        celda_cubiertos.font = Font(
            bold=True,
            size=8,
        )


        ws.row_dimensions[
            fila_excel
        ].height = 42


        fila_excel += 1


    # ========================================================
    # ANCHOS
    # ========================================================

    ws.column_dimensions[
        "A"
    ].width = 28


    ws.column_dimensions[
        "B"
    ].width = 15


    ws.column_dimensions[
        "C"
    ].width = 14


    for indice_mes in range(
        len(
            meses
        )
    ):

        letra = (
            get_column_letter(
                4 + indice_mes
            )
        )


        ws.column_dimensions[
            letra
        ].width = 15


    indice_totales = (
        4
        +
        len(
            meses
        )
    )


    ws.column_dimensions[
        get_column_letter(
            indice_totales
        )
    ].width = 17


    ws.column_dimensions[
        get_column_letter(
            indice_totales + 1
        )
    ].width = 14


    ws.column_dimensions[
        get_column_letter(
            indice_totales + 2
        )
    ].width = 16


    ws.column_dimensions[
        get_column_letter(
            indice_totales + 3
        )
    ].width = 14


    # ========================================================
    # SCROLL NORMAL
    # ========================================================

    # No congelamos ninguna fila ni columna.
    #
    # De esta manera, al desplazarse hacia abajo
    # en Excel, se mueve toda la hoja de forma normal:
    #
    # - logo;
    # - cabecera azul;
    # - resumen;
    # - encabezados de la tabla;
    # - filas.
    #
    # Antes utilizábamos:
    #
    # ws.freeze_panes = f"D{fila_datos_inicio}"
    #
    # y por eso la parte superior permanecía fija.

    ws.freeze_panes = None


    # ========================================================
    # AUTOFILTRO
    # ========================================================

    ultima_fila_datos = max(
        fila_encabezado,
        fila_excel - 1,
    )


    ws.auto_filter.ref = (
        f"A{fila_encabezado}:"
        f"{ultima_columna}"
        f"{ultima_fila_datos}"
    )


    # ========================================================
    # LEYENDA
    # ========================================================

    fila_leyenda = (
        ultima_fila_datos
        + 2
    )


    celda_leyenda = ws.cell(
        row=fila_leyenda,
        column=1,
        value="Leyenda",
    )


    celda_leyenda.font = Font(
        bold=True,
        color=azul_oscuro,
    )


    leyenda = [

        (
            "Al día",
            color_al_dia,
            negro,
        ),

        (
            "Parcial",
            color_parcial,
            negro,
        ),

        (
            "Pendiente",
            color_pendiente,
            negro,
        ),

        (
            "Exonerado",
            color_exonerado,
            negro,
        ),

        (
            "Sin registro",
            color_sin_registro,
            negro,
        ),

        (
            "Próximo",
            color_proximo,
            negro,
        ),

        (
            "Sin tarifa",
            color_sin_tarifa,
            blanco,
        ),

    ]


    columna_leyenda = 2


    for (
        nombre_estado,
        color,
        color_texto,
    ) in leyenda:

        celda = ws.cell(
            row=fila_leyenda,
            column=columna_leyenda,
        )


        celda.value = (
            nombre_estado
        )


        celda.fill = (
            PatternFill(
                fill_type="solid",
                fgColor=color,
            )
        )


        celda.font = Font(
            bold=True,
            color=color_texto,
            size=8,
        )


        celda.alignment = (
            Alignment(
                horizontal="center",
                vertical="center",
            )
        )


        celda.border = (
            borde_celda
        )


        columna_leyenda += 1


    # ========================================================
    # PIE
    # ========================================================

    fila_exportacion = (
        fila_leyenda + 2
    )


    ws.merge_cells(
        start_row=fila_exportacion,
        start_column=1,
        end_row=fila_exportacion,
        end_column=total_columnas_visual,
    )


    celda_exportacion = ws.cell(
        row=fila_exportacion,
        column=1,
    )


    celda_exportacion.value = (
        "Exportado el "
        +
        timezone.localtime()
        .strftime(
            "%d/%m/%Y %H:%M"
        )
    )


    celda_exportacion.font = Font(
        italic=True,
        color="6C757D",
        size=8,
    )


    celda_exportacion.alignment = (
        Alignment(
            horizontal="right",
        )
    )


    # ========================================================
    # CONFIGURACIÓN DE IMPRESIÓN
    # ========================================================

    ws.page_setup.orientation = (
        "landscape"
    )


    ws.page_setup.fitToWidth = 1

    ws.page_setup.fitToHeight = 0


    ws.sheet_properties.pageSetUpPr.fitToPage = (
        True
    )


    # Esto solo aplica al imprimir.
    # NO congela filas durante el uso normal
    # del archivo Excel.

    ws.print_title_rows = (
        f"{fila_encabezado}:"
        f"{fila_encabezado}"
    )


    ws.print_area = (
        f"A1:"
        f"{ultima_columna_visual}"
        f"{fila_exportacion}"
    )


    ws.page_margins.left = 0.25

    ws.page_margins.right = 0.25

    ws.page_margins.top = 0.5

    ws.page_margins.bottom = 0.5


    # ========================================================
    # GUARDAR
    # ========================================================

    output = io.BytesIO()


    wb.save(
        output
    )


    output.seek(
        0
    )


    nombre_archivo = (
        f"reporte_mensualidades_"
        f"{año}_"
        f"{mes_inicio:02d}-"
        f"{mes_fin:02d}.xlsx"
    )


    response = HttpResponse(
        output.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        ),
    )


    response[
        "Content-Disposition"
    ] = (
        f'attachment; '
        f'filename="{nombre_archivo}"'
    )


    return response

@user_passes_test(es_admin)
def exportar_pagos_pdf(request):
    """
    Exporta el reporte de mensualidades a PDF.

    Utiliza exactamente el mismo motor financiero
    del reporte web y del Excel.

    Respeta:
    - tarifas históricas;
    - pagos activos;
    - pagos anulados;
    - pagos parciales;
    - exoneraciones;
    - períodos sin registro;
    - períodos próximos;
    - filtros aplicados.
    """

    import io
    import os

    from django.conf import settings
    from django.http import FileResponse

    from reportlab.lib import colors

    from reportlab.lib.enums import (
        TA_CENTER,
        TA_LEFT,
        TA_RIGHT,
    )

    from reportlab.lib.pagesizes import (
        landscape,
        letter,
    )

    from reportlab.lib.styles import (
        ParagraphStyle,
        getSampleStyleSheet,
    )

    from reportlab.platypus import (
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    from xml.sax.saxutils import escape


    # ========================================================
    # FILTROS
    # ========================================================

    hoy = timezone.localdate()


    año = (
        request.GET.get("año")
        or hoy.year
    )


    mes_inicio = (
        request.GET.get("mes_inicio")
        or 1
    )


    mes_fin = (
        request.GET.get("mes_fin")
        or 12
    )


    categoria = (
        request.GET
        .get(
            "categoria",
            "",
        )
        .strip()
    )


    nombre = (
        request.GET
        .get(
            "nombre",
            "",
        )
        .strip()
    )


    cedula = (
        request.GET
        .get(
            "cedula",
            "",
        )
        .strip()
    )


    estado = (
        request.GET
        .get(
            "estado",
            "",
        )
        .strip()
    )


    # ========================================================
    # MOTOR FINANCIERO
    # ========================================================

    reporte = (
        _construir_reporte_financiero(
            año=año,
            mes_inicio=mes_inicio,
            mes_fin=mes_fin,
            categoria=categoria,
            nombre=nombre,
            cedula=cedula,
            estado_filtro=estado,
        )
    )


    año = reporte["año"]

    mes_inicio = reporte["mes_inicio"]

    mes_fin = reporte["mes_fin"]

    filas = reporte["filas"]

    meses = reporte["meses"]

    totales = reporte["totales"]


    # ========================================================
    # HELPERS
    # ========================================================

    def formato_numero(
        valor,
    ):
        """
        Formato visual con separador de miles
        y dos decimales.
        """

        try:

            return (
                f"{valor:,.2f}"
            )

        except (
            TypeError,
            ValueError,
        ):

            return "0.00"


    def texto_seguro(
        valor,
    ):
        """
        Escapa texto para utilizarlo
        dentro de Paragraph de ReportLab.
        """

        if valor is None:

            return ""

        return escape(
            str(
                valor
            )
        )


    # ========================================================
    # BUFFER Y DOCUMENTO
    # ========================================================

    buffer = io.BytesIO()


    pagina = landscape(
        letter
    )


    ancho_pagina, alto_pagina = (
        pagina
    )


    margen_izquierdo = 22

    margen_derecho = 22

    margen_superior = 24

    margen_inferior = 34


    doc = SimpleDocTemplate(
        buffer,
        pagesize=pagina,
        rightMargin=margen_derecho,
        leftMargin=margen_izquierdo,
        topMargin=margen_superior,
        bottomMargin=margen_inferior,
        title=(
            f"Reporte de mensualidades "
            f"{año}"
        ),
        author="Escuela Deportiva OLYMPO",
    )


    ancho_util = (
        ancho_pagina
        - margen_izquierdo
        - margen_derecho
    )


    # ========================================================
    # COLORES
    # ========================================================

    azul_oscuro = colors.HexColor(
        "#2A73B6"
    )

    azul_olympo = colors.HexColor(
        "#158EFF"
    )

    negro = colors.HexColor(
        "#212529"
    )

    gris_texto = colors.HexColor(
        "#6C757D"
    )

    gris_borde = colors.HexColor(
        "#DEE2E6"
    )

    gris_claro = colors.HexColor(
        "#F8F9FA"
    )


    color_al_dia = colors.HexColor(
        "#D1E7DD"
    )

    color_parcial = colors.HexColor(
        "#FFF3CD"
    )

    color_pendiente = colors.HexColor(
        "#F8D7DA"
    )

    color_exonerado = colors.HexColor(
        "#CFF4FC"
    )

    color_sin_registro = colors.HexColor(
        "#E2E3E5"
    )

    color_proximo = colors.HexColor(
        "#F8F9FA"
    )

    color_sin_tarifa = colors.HexColor(
        "#343A40"
    )


    # ========================================================
    # ESTILOS
    # ========================================================

    estilos = getSampleStyleSheet()


    estilo_titulo = ParagraphStyle(
        "TituloOLYMPO",
        parent=estilos["Normal"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=colors.white,
        alignment=TA_LEFT,
        spaceAfter=0,
    )


    estilo_subtitulo = ParagraphStyle(
        "SubtituloOLYMPO",
        parent=estilos["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.white,
        alignment=TA_LEFT,
    )


    estilo_filtro = ParagraphStyle(
        "Filtro",
        parent=estilos["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=gris_texto,
        alignment=TA_LEFT,
    )


    estilo_resumen_label = ParagraphStyle(
        "ResumenLabel",
        parent=estilos["Normal"],
        fontName="Helvetica-Bold",
        fontSize=6.5,
        leading=8,
        textColor=azul_oscuro,
        alignment=TA_CENTER,
    )


    estilo_resumen_valor = ParagraphStyle(
        "ResumenValor",
        parent=estilos["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=negro,
        alignment=TA_CENTER,
    )


    estilo_header_tabla = ParagraphStyle(
        "HeaderTabla",
        parent=estilos["Normal"],
        fontName="Helvetica-Bold",
        fontSize=6.4,
        leading=7.2,
        textColor=colors.white,
        alignment=TA_CENTER,
    )


    estilo_nombre = ParagraphStyle(
        "NombreAtleta",
        parent=estilos["Normal"],
        fontName="Helvetica-Bold",
        fontSize=6.2,
        leading=7.2,
        textColor=negro,
        alignment=TA_LEFT,
    )


    estilo_celda = ParagraphStyle(
        "Celda",
        parent=estilos["Normal"],
        fontName="Helvetica",
        fontSize=6,
        leading=7,
        textColor=negro,
        alignment=TA_CENTER,
    )


    estilo_estado = ParagraphStyle(
        "Estado",
        parent=estilos["Normal"],
        fontName="Helvetica-Bold",
        fontSize=6,
        leading=6.8,
        textColor=negro,
        alignment=TA_CENTER,
    )


    estilo_estado_blanco = ParagraphStyle(
        "EstadoBlanco",
        parent=estilo_estado,
        textColor=colors.white,
    )


    estilo_leyenda = ParagraphStyle(
        "Leyenda",
        parent=estilos["Normal"],
        fontName="Helvetica",
        fontSize=6.3,
        leading=7.5,
        textColor=negro,
        alignment=TA_CENTER,
    )


    estilo_vacio = ParagraphStyle(
        "Vacio",
        parent=estilos["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=gris_texto,
        alignment=TA_CENTER,
    )


    # ========================================================
    # STORY
    # ========================================================

    elementos = []


    # ========================================================
    # CABECERA PRINCIPAL
    # ========================================================

    logo_path = os.path.join(
        settings.BASE_DIR,
        "static",
        "img",
        "logo-olympo.jpeg",
    )


    logo = ""


    if os.path.exists(
        logo_path
    ):

        try:

            logo = Image(
                logo_path,
                width=72,
                height=72,
            )

        except Exception:

            logo = ""


    titulo = Paragraph(
        (
            "Escuela Deportiva OLYMPO"
            "<br/>"
            f"<font size='9'>"
            f"Reporte de mensualidades - "
            f"{texto_seguro(_MESES_REPORTE[mes_inicio])} "
            f"a "
            f"{texto_seguro(_MESES_REPORTE[mes_fin])} "
            f"{año}"
            f"</font>"
        ),
        estilo_titulo,
    )


    header = Table(
        [
            [
                logo,
                titulo,
            ]
        ],
        colWidths=[
            82,
            ancho_util - 82,
        ],
        rowHeights=[
            78,
        ],
    )


    header.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, 0),
                    azul_oscuro,
                ),

                (
                    "BACKGROUND",
                    (1, 0),
                    (1, 0),
                    azul_olympo,
                ),

                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),

                (
                    "ALIGN",
                    (0, 0),
                    (0, 0),
                    "CENTER",
                ),

                (
                    "LEFTPADDING",
                    (1, 0),
                    (1, 0),
                    14,
                ),

                (
                    "RIGHTPADDING",
                    (1, 0),
                    (1, 0),
                    10,
                ),

                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    4,
                ),

                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    4,
                ),
            ]
        )
    )


    elementos.append(
        header
    )


    elementos.append(
        Spacer(
            1,
            7,
        )
    )


    # ========================================================
    # FILTROS APLICADOS
    # ========================================================

    filtros = []


    if categoria:

        filtros.append(
            f"Categoría: "
            f"{texto_seguro(categoria)}"
        )


    if nombre:

        filtros.append(
            f"Nombre: "
            f"{texto_seguro(nombre)}"
        )


    if cedula:

        filtros.append(
            f"Cédula: "
            f"{texto_seguro(cedula)}"
        )


    if reporte["filtros"]["estado"]:

        estado_nombre = (
            _NOMBRES_ESTADO_REPORTE
            .get(
                reporte["filtros"]["estado"],
                reporte["filtros"]["estado"],
            )
        )


        filtros.append(
            f"Estado: "
            f"{texto_seguro(estado_nombre)}"
        )


    if filtros:

        texto_filtros = (
            "<b>Filtros:</b> "
            +
            " | ".join(
                filtros
            )
        )

    else:

        texto_filtros = (
            "<b>Filtros:</b> "
            "todos los atletas"
        )


    elementos.append(
        Paragraph(
            texto_filtros,
            estilo_filtro,
        )
    )


    elementos.append(
        Spacer(
            1,
            7,
        )
    )


    # ========================================================
    # RESUMEN GENERAL
    # ========================================================

    resumen_labels = [

        Paragraph(
            "Atletas",
            estilo_resumen_label,
        ),

        Paragraph(
            "Recaudado Bs",
            estilo_resumen_label,
        ),

        Paragraph(
            "Equiv. USD",
            estilo_resumen_label,
        ),

        Paragraph(
            "Pendiente USD",
            estilo_resumen_label,
        ),

        Paragraph(
            "Cubiertos / Gestionados",
            estilo_resumen_label,
        ),

    ]


    resumen_valores = [

        Paragraph(
            str(
                reporte[
                    "total_atletas"
                ]
            ),
            estilo_resumen_valor,
        ),

        Paragraph(
            (
                "Bs "
                f"{formato_numero(totales['pagado_bs'])}"
            ),
            estilo_resumen_valor,
        ),

        Paragraph(
            (
                "$"
                f"{formato_numero(totales['pagado_usd'])}"
            ),
            estilo_resumen_valor,
        ),

        Paragraph(
            (
                "$"
                f"{formato_numero(totales['pendiente_usd'])}"
            ),
            estilo_resumen_valor,
        ),

        Paragraph(
            (
                f"{totales['meses_cubiertos']}"
                f" / "
                f"{totales['meses_gestionados']}"
            ),
            estilo_resumen_valor,
        ),

    ]


    tabla_resumen = Table(
        [
            resumen_labels,
            resumen_valores,
        ],
        colWidths=[
            ancho_util / 5
        ] * 5,
    )


    tabla_resumen.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor(
                        "#EAF3FB"
                    ),
                ),

                (
                    "BACKGROUND",
                    (0, 1),
                    (-1, 1),
                    colors.white,
                ),

                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    gris_borde,
                ),

                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),

                (
                    "ALIGN",
                    (0, 0),
                    (-1, -1),
                    "CENTER",
                ),

                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    4,
                ),

                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    4,
                ),
            ]
        )
    )


    elementos.append(
        tabla_resumen
    )


    elementos.append(
        Spacer(
            1,
            7,
        )
    )


    # ========================================================
    # RESUMEN DE ESTADOS
    # ========================================================

    estados_resumen = [

        (
            "AD",
            "Al día",
            totales[
                "estados"
            ][
                "al_dia"
            ],
            color_al_dia,
            negro,
        ),

        (
            "PA",
            "Parcial",
            totales[
                "estados"
            ][
                "parcial"
            ],
            color_parcial,
            negro,
        ),

        (
            "PE",
            "Pendiente",
            totales[
                "estados"
            ][
                "pendiente"
            ],
            color_pendiente,
            negro,
        ),

        (
            "EX",
            "Exonerado",
            totales[
                "estados"
            ][
                "exonerado"
            ],
            color_exonerado,
            negro,
        ),

        (
            "SR",
            "Sin registro",
            totales[
                "estados"
            ][
                "sin_registro"
            ],
            color_sin_registro,
            negro,
        ),

        (
            "PR",
            "Próximo",
            totales[
                "estados"
            ][
                "proximo"
            ],
            color_proximo,
            negro,
        ),

        (
            "ST",
            "Sin tarifa",
            totales[
                "estados"
            ][
                "sin_tarifa"
            ],
            color_sin_tarifa,
            colors.white,
        ),

    ]


    fila_estados = []


    for (
        codigo,
        etiqueta,
        cantidad,
        color_fondo,
        color_texto,
    ) in estados_resumen:

        estilo_temporal = ParagraphStyle(
            f"estado_{codigo}",
            parent=estilo_leyenda,
            textColor=color_texto,
            fontName="Helvetica-Bold",
        )


        fila_estados.append(
            Paragraph(
                (
                    f"<b>{codigo}</b> "
                    f"{texto_seguro(etiqueta)}"
                    f"<br/>"
                    f"<font size='7'>"
                    f"{cantidad}"
                    f"</font>"
                ),
                estilo_temporal,
            )
        )


    tabla_estados = Table(
        [
            fila_estados
        ],
        colWidths=[
            ancho_util / 7
        ] * 7,
    )


    estilo_tabla_estados = [
        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.4,
            gris_borde,
        ),

        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "MIDDLE",
        ),

        (
            "ALIGN",
            (0, 0),
            (-1, -1),
            "CENTER",
        ),

        (
            "TOPPADDING",
            (0, 0),
            (-1, -1),
            4,
        ),

        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            4,
        ),
    ]


    for indice, estado_resumen in enumerate(
        estados_resumen
    ):

        estilo_tabla_estados.append(
            (
                "BACKGROUND",
                (indice, 0),
                (indice, 0),
                estado_resumen[3],
            )
        )


    tabla_estados.setStyle(
        TableStyle(
            estilo_tabla_estados
        )
    )


    elementos.append(
        tabla_estados
    )


    elementos.append(
        Spacer(
            1,
            9,
        )
    )


    # ========================================================
    # TABLA PRINCIPAL
    # ========================================================

    encabezados = [
        "Atleta",
        "C.I.",
        "Cat.",
    ]


    for mes in meses:

        encabezados.append(
            mes[
                "abreviatura"
            ].title()
        )


    encabezados += [
        "Bs",
        "USD",
        "Pend.",
        "Cob.",
    ]


    datos_tabla = [
        [
            Paragraph(
                texto_seguro(
                    encabezado
                ),
                estilo_header_tabla,
            )

            for encabezado
            in encabezados
        ]
    ]


    # ========================================================
    # ANCHOS DINÁMICOS
    # ========================================================

    ancho_nombre = 92

    ancho_cedula = 50

    ancho_categoria = 43

    ancho_bs = 60

    ancho_usd = 38

    ancho_pendiente = 42

    ancho_cobertura = 38


    ancho_fijo = (
        ancho_nombre
        + ancho_cedula
        + ancho_categoria
        + ancho_bs
        + ancho_usd
        + ancho_pendiente
        + ancho_cobertura
    )


    cantidad_meses = max(
        1,
        len(
            meses
        ),
    )


    ancho_disponible_meses = (
        ancho_util
        - ancho_fijo
    )


    ancho_mes = (
        ancho_disponible_meses
        / cantidad_meses
    )


    # Evita meses gigantes al exportar
    # solamente uno o dos meses.

    ancho_mes = min(
        46,
        ancho_mes,
    )


    anchos_columnas = [
        ancho_nombre,
        ancho_cedula,
        ancho_categoria,
    ]


    anchos_columnas += [
        ancho_mes
    ] * len(
        meses
    )


    anchos_columnas += [
        ancho_bs,
        ancho_usd,
        ancho_pendiente,
        ancho_cobertura,
    ]


    # ========================================================
    # ESTILOS INDIVIDUALES DE ESTADO
    # ========================================================

    mapa_colores_estado = {

        "al_dia":
            color_al_dia,

        "parcial":
            color_parcial,

        "pendiente":
            color_pendiente,

        "exonerado":
            color_exonerado,

        "sin_registro":
            color_sin_registro,

        "proximo":
            color_proximo,

        "sin_tarifa":
            color_sin_tarifa,

    }


    comandos_estilo = [

        (
            "BACKGROUND",
            (0, 0),
            (-1, 0),
            negro,
        ),

        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.35,
            gris_borde,
        ),

        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "MIDDLE",
        ),

        (
            "ALIGN",
            (1, 1),
            (-1, -1),
            "CENTER",
        ),

        (
            "LEFTPADDING",
            (0, 0),
            (-1, -1),
            2,
        ),

        (
            "RIGHTPADDING",
            (0, 0),
            (-1, -1),
            2,
        ),

        (
            "TOPPADDING",
            (0, 0),
            (-1, -1),
            3,
        ),

        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            3,
        ),
    ]


    # ========================================================
    # DATOS
    # ========================================================

    for indice_fila, fila in enumerate(
        filas,
        start=1,
    ):

        fila_pdf = [

            Paragraph(
                texto_seguro(
                    fila[
                        "nombre_completo"
                    ]
                ),
                estilo_nombre,
            ),

            Paragraph(
                texto_seguro(
                    fila[
                        "cedula"
                    ] or "-"
                ),
                estilo_celda,
            ),

            Paragraph(
                texto_seguro(
                    fila[
                        "categoria"
                    ] or "-"
                ),
                estilo_celda,
            ),

        ]


        # ----------------------------------------
        # MESES
        # ----------------------------------------

        for indice_mes, periodo in enumerate(
            fila[
                "periodos"
            ]
        ):

            codigo_estado = (
                periodo[
                    "estado_codigo"
                ]
            )


            if codigo_estado == "al_dia":

                contenido = (
                    "<b>AD</b>"
                    "<br/>"
                    f"<font size='5'>"
                    f"${periodo['pagado_usd']:.2f}"
                    f"</font>"
                )


            elif codigo_estado == "parcial":

                contenido = (
                    "<b>PA</b>"
                    "<br/>"
                    f"<font size='5'>"
                    f"${periodo['pagado_usd']:.2f}"
                    f"</font>"
                )


            elif codigo_estado == "pendiente":

                contenido = (
                    "<b>PE</b>"
                    "<br/>"
                    f"<font size='5'>"
                    f"${periodo['saldo_usd']:.2f}"
                    f"</font>"
                )


            elif codigo_estado == "exonerado":

                contenido = (
                    "<b>EX</b>"
                )


            elif codigo_estado == "sin_registro":

                contenido = (
                    "<b>SR</b>"
                )


            elif codigo_estado == "proximo":

                contenido = (
                    "<b>PR</b>"
                )


            else:

                contenido = (
                    "<b>ST</b>"
                )


            if (
                codigo_estado
                == "sin_tarifa"
            ):

                estilo_periodo = (
                    estilo_estado_blanco
                )

            else:

                estilo_periodo = (
                    estilo_estado
                )


            fila_pdf.append(
                Paragraph(
                    contenido,
                    estilo_periodo,
                )
            )


            columna_estado = (
                3
                + indice_mes
            )


            comandos_estilo.append(
                (
                    "BACKGROUND",
                    (
                        columna_estado,
                        indice_fila,
                    ),
                    (
                        columna_estado,
                        indice_fila,
                    ),
                    mapa_colores_estado[
                        codigo_estado
                    ],
                )
            )


        # ----------------------------------------
        # TOTALES
        # ----------------------------------------

        fila_pdf += [

            Paragraph(
                (
                    "Bs "
                    f"{formato_numero(fila['total_pagado_bs'])}"
                ),
                estilo_celda,
            ),

            Paragraph(
                (
                    "$"
                    f"{formato_numero(fila['total_pagado_usd'])}"
                ),
                estilo_celda,
            ),

            Paragraph(
                (
                    "$"
                    f"{formato_numero(fila['total_pendiente_usd'])}"
                ),
                estilo_celda,
            ),

            Paragraph(
                (
                    f"{fila['meses_cubiertos']}"
                    f"/"
                    f"{fila['meses_gestionados']}"
                ),
                estilo_celda,
            ),

        ]


        datos_tabla.append(
            fila_pdf
        )


    # ========================================================
    # MOSTRAR TABLA O MENSAJE VACÍO
    # ========================================================

    if filas:

        tabla_principal = Table(
            datos_tabla,
            colWidths=anchos_columnas,
            repeatRows=1,
            hAlign="CENTER",
            splitByRow=1,
        )


        tabla_principal.setStyle(
            TableStyle(
                comandos_estilo
            )
        )


        elementos.append(
            tabla_principal
        )


    else:

        elementos.append(
            Spacer(
                1,
                25,
            )
        )


        elementos.append(
            Paragraph(
                (
                    "No se encontraron atletas "
                    "que coincidan con los filtros seleccionados."
                ),
                estilo_vacio,
            )
        )


    # ========================================================
    # LEYENDA
    # ========================================================

    elementos.append(
        Spacer(
            1,
            10,
        )
    )


    leyenda_datos = [
        [
            Paragraph(
                "<b>AD</b> Al día",
                estilo_leyenda,
            ),

            Paragraph(
                "<b>PA</b> Parcial",
                estilo_leyenda,
            ),

            Paragraph(
                "<b>PE</b> Pendiente",
                estilo_leyenda,
            ),

            Paragraph(
                "<b>EX</b> Exonerado",
                estilo_leyenda,
            ),

            Paragraph(
                "<b>SR</b> Sin registro",
                estilo_leyenda,
            ),

            Paragraph(
                "<b>PR</b> Próximo",
                estilo_leyenda,
            ),

            Paragraph(
                "<b>ST</b> Sin tarifa",
                estilo_estado_blanco,
            ),
        ]
    ]


    tabla_leyenda = Table(
        leyenda_datos,
        colWidths=[
            ancho_util / 7
        ] * 7,
    )


    tabla_leyenda.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, 0),
                    color_al_dia,
                ),

                (
                    "BACKGROUND",
                    (1, 0),
                    (1, 0),
                    color_parcial,
                ),

                (
                    "BACKGROUND",
                    (2, 0),
                    (2, 0),
                    color_pendiente,
                ),

                (
                    "BACKGROUND",
                    (3, 0),
                    (3, 0),
                    color_exonerado,
                ),

                (
                    "BACKGROUND",
                    (4, 0),
                    (4, 0),
                    color_sin_registro,
                ),

                (
                    "BACKGROUND",
                    (5, 0),
                    (5, 0),
                    color_proximo,
                ),

                (
                    "BACKGROUND",
                    (6, 0),
                    (6, 0),
                    color_sin_tarifa,
                ),

                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    gris_borde,
                ),

                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),

                (
                    "ALIGN",
                    (0, 0),
                    (-1, -1),
                    "CENTER",
                ),

                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    4,
                ),

                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    4,
                ),
            ]
        )
    )


    elementos.append(
        tabla_leyenda
    )


    # ========================================================
    # PIE DE PÁGINA
    # ========================================================

    fecha_exportacion = (
        timezone.localtime()
        .strftime(
            "%d/%m/%Y %H:%M"
        )
    )


    def pie_pagina(
        canvas_pdf,
        documento,
    ):

        canvas_pdf.saveState()


        # Línea superior del pie

        canvas_pdf.setStrokeColor(
            gris_borde
        )

        canvas_pdf.setLineWidth(
            0.5
        )

        canvas_pdf.line(
            margen_izquierdo,
            25,
            ancho_pagina
            - margen_derecho,
            25,
        )


        # Fecha

        canvas_pdf.setFont(
            "Helvetica",
            6.5,
        )

        canvas_pdf.setFillColor(
            gris_texto
        )

        canvas_pdf.drawString(
            margen_izquierdo,
            14,
            (
                f"Exportado: "
                f"{fecha_exportacion}"
            ),
        )


        # Página

        canvas_pdf.drawRightString(
            ancho_pagina
            - margen_derecho,
            14,
            (
                f"Página "
                f"{canvas_pdf.getPageNumber()}"
            ),
        )


        # Marca central

        canvas_pdf.setFillColor(
            azul_oscuro
        )

        canvas_pdf.setFont(
            "Helvetica-Bold",
            6.5,
        )

        canvas_pdf.drawCentredString(
            ancho_pagina / 2,
            14,
            "OLYMPO",
        )


        canvas_pdf.restoreState()


    # ========================================================
    # GENERAR PDF
    # ========================================================

    doc.build(
        elementos,
        onFirstPage=pie_pagina,
        onLaterPages=pie_pagina,
    )


    buffer.seek(
        0
    )


    # ========================================================
    # RESPUESTA
    # ========================================================

    nombre_archivo = (
        f"reporte_mensualidades_"
        f"{año}_"
        f"{mes_inicio:02d}-"
        f"{mes_fin:02d}.pdf"
    )


    return FileResponse(
        buffer,
        as_attachment=True,
        filename=nombre_archivo,
        content_type="application/pdf",
    )

@user_passes_test(lambda u: es_admin(u) or es_entrenador(u))
def reporte_atletas_view(request):
    categorias = [
        'U9',
        'U11',
        'U13',
        'U15',
        'U17',
        'U19',
        'U21',
        'U23',
        'Libre'
    ]

    atletas = Atleta.objects.all()

    cedula = request.GET.get('cedula', '').strip()
    nombre = request.GET.get('nombre', '').strip()
    categoria = request.GET.get('categoria', '')
    edad_min = request.GET.get('edad_min')
    edad_max = request.GET.get('edad_max')
    sexo = request.GET.get('sexo', '').strip()

    if cedula:
        atletas = atletas.filter(
            cedula__icontains=cedula
        )

    if nombre:
        atletas = (
            atletas.filter(nombre__icontains=nombre)
            |
            atletas.filter(apellido__icontains=nombre)
        )

    if categoria:
        atletas = atletas.filter(
            categoria=categoria
        )

    if edad_min:
        atletas = atletas.filter(
            fecha_nacimiento__year__lte=
            timezone.localdate().year - int(edad_min)
        )

    if edad_max:
        atletas = atletas.filter(
            fecha_nacimiento__year__gte=
            timezone.localdate().year - int(edad_max)
        )

    if sexo:
        atletas = atletas.filter(
            sexo__iexact=sexo
        )

    años_disponibles = sorted({
        atleta.fecha_registro.year
        for atleta in Atleta.objects.all()
    })

    # Orden estable para evitar
    # UnorderedObjectListWarning en la paginación
    atletas = atletas.order_by(
        'apellido',
        'nombre',
        'id'
    )

    # PAGINACIÓN
    from django.core.paginator import Paginator

    paginator = Paginator(
        atletas,
        15
    )

    page_number = request.GET.get('page')
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

    return render(
        request,
        'reportes/reporte_atletas.html',
        context
    )

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
        atletas = atletas.filter(fecha_nacimiento__year__lte=timezone.localdate().year - int(edad_min))
    if edad_max:
        atletas = atletas.filter(fecha_nacimiento__year__gte=timezone.localdate().year - int(edad_max))
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
        fecha = timezone.localtime().strftime("%d/%m/%Y %H:%M")
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
        fecha = timezone.localtime().strftime("%d/%m/%Y %H:%M")
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
        fecha = timezone.localtime().strftime("%d/%m/%Y %H:%M")
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

    equipos = (
        Equipo.objects
        .all()
        .annotate(num_atletas=Count("atletas"))
    )

    # filtro por nombre
    if nombre:
        equipos = equipos.filter(
            nombre__icontains=nombre
        )

    # filtro por sexo
    sexo_normalizado = ""

    if sexo_param:
        s = sexo_param.lower()

        if s in (
            "masculino",
            "femenino",
            "mixto"
        ):
            sexo_normalizado = s

        elif s == "m":
            sexo_normalizado = "masculino"

        elif s == "f":
            sexo_normalizado = "femenino"

    if sexo_normalizado:
        equipos = equipos.filter(
            sexo_equipo=sexo_normalizado
        )

    # filtro por entrenador
    if entrenador_id and entrenador_id.isdigit():
        equipos = equipos.filter(
            entrenador__id=int(entrenador_id)
        )

    # Orden estable para evitar
    # UnorderedObjectListWarning en la paginación
    equipos = equipos.order_by(
        "nombre",
        "id"
    )

    paginator = Paginator(
        equipos,
        10
    )

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    context = {
        "page_obj": page_obj,
        "entrenadores": (
            Entrenador.objects
            .all()
            .order_by(
                "nombre",
                "apellido"
            )
        ),
        "nombre": nombre,
        "sexo": sexo_normalizado or sexo_param,
        "entrenador_id": entrenador_id,
    }

    return render(
        request,
        "reportes/reporte_equipos.html",
        context
    )

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
        fecha = timezone.localtime().strftime("%d/%m/%Y %H:%M")
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
    entrenadores = Entrenador.objects.all().order_by(
        "apellido",
        "nombre",
        "id"
    )

    # PAGINACIÓN
    paginator = Paginator(
        entrenadores,
        10
    )

    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "entrenadores": page_obj,
        "page_obj": page_obj,
    }

    return render(
        request,
        "reportes/reporte_entrenadores.html",
        context
    )

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
        fecha = timezone.localtime().strftime("%d/%m/%Y %H:%M")
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
        fecha = timezone.localtime().strftime("%d/%m/%Y %H:%M")
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
        fecha = timezone.localtime().strftime("%d/%m/%Y %H:%M")
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
    ws["C4"] = f"Generado: {timezone.localtime().strftime('%d/%m/%Y %H:%M')}"
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
    administradores = Administrador.objects.all().order_by(
        "apellido",
        "nombre",
        "id"
    )

    return render(
        request,
        "administradores/lista.html",
        {
            "administradores": administradores,
        }
    )

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
            try:
                crear_usuario_para_administrador(
                    administrador,
                    username,
                    password,
                    email
                )
            except IntegrityError:
                usuario_form.add_error(
                    'username',
                    'Ya existe una cuenta con este nombre de usuario.'
                )
            else:
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

    motivo_bloqueo = None

    # No permitir que un administrador elimine su propia cuenta
    if administrador.usuario_id == request.user.id:
        motivo_bloqueo = (
            "No puedes eliminar tu propia cuenta de administrador "
            "mientras tienes la sesión iniciada."
        )

    # No permitir eliminar el último administrador activo
    elif administrador.usuario.is_active:
        otros_administradores_activos = Administrador.objects.filter(
            usuario__is_active=True
        ).exclude(id=administrador.id)

        if not otros_administradores_activos.exists():
            motivo_bloqueo = (
                "No puedes eliminar el último administrador activo del sistema. "
                "Primero debes crear o activar otro administrador."
            )

    if request.method == "POST":
        if motivo_bloqueo:
            return render(
                request,
                "administradores/eliminar.html",
                {
                    "administrador": administrador,
                    "motivo_bloqueo": motivo_bloqueo,
                },
                status=403,
            )

        usuario = administrador.usuario

        with transaction.atomic():
            administrador.delete()
            eliminar_usuario_sin_perfil(usuario)

        return redirect("lista_administradores")

    return render(
        request,
        "administradores/eliminar.html",
        {
            "administrador": administrador,
            "motivo_bloqueo": motivo_bloqueo,
        },
    )

@user_passes_test(es_admin)
def lista_usuarios(request):
    rol_filtro = request.GET.get('rol', '')
    estado_filtro = request.GET.get('estado', '')
    nombre_filtro = request.GET.get('nombre', '').strip()

    usuarios = []

    # --- Entrenadores ---
    for entrenador in Entrenador.objects.select_related('user'):
        if not entrenador.user:
            continue

        usuarios.append({
            'id': entrenador.id,
            'nombre': entrenador.nombre,
            'apellido': entrenador.apellido,
            'usuario': entrenador.user.username,
            'email': entrenador.user.email,
            'rol': 'Entrenador',
            'estado': (
                'Activo'
                if entrenador.user.is_active
                else 'Inactivo'
            ),
        })

    # --- Atletas ---
    for atleta in Atleta.objects.select_related('user'):
        if not atleta.user:
            continue

        usuarios.append({
            'id': atleta.id,
            'nombre': atleta.nombre,
            'apellido': atleta.apellido,
            'usuario': atleta.user.username,
            'email': atleta.user.email,
            'rol': 'Atleta',
            'estado': (
                'Activo'
                if atleta.user.is_active
                else 'Inactivo'
            ),
        })

    # --- Administradores ---
    for administrador in Administrador.objects.select_related('usuario'):
        if not administrador.usuario:
            continue

        usuarios.append({
            'id': administrador.id,
            'nombre': administrador.nombre,
            'apellido': administrador.apellido,
            'usuario': administrador.usuario.username,
            'email': administrador.usuario.email,
            'rol': 'Administrador',
            'estado': (
                'Activo'
                if administrador.usuario.is_active
                else 'Inactivo'
            ),
        })

    # --- FILTROS ---
    if rol_filtro:
        usuarios = [
            usuario
            for usuario in usuarios
            if usuario['rol'] == rol_filtro
        ]

    if estado_filtro:
        usuarios = [
            usuario
            for usuario in usuarios
            if usuario['estado'] == estado_filtro
        ]

    if nombre_filtro:
        termino = nombre_filtro.lower()

        usuarios = [
            usuario
            for usuario in usuarios
            if (
                termino in usuario['nombre'].lower()
                or termino in usuario['apellido'].lower()
            )
        ]

    # Orden estable antes de enviarlos al template
    usuarios.sort(
        key=lambda usuario: (
            usuario['apellido'].lower(),
            usuario['nombre'].lower(),
            usuario['usuario'].lower(),
        )
    )

    return render(
        request,
        'usuarios/lista.html',
        {
            'usuarios': usuarios,
            'rol_filtro': rol_filtro,
            'estado_filtro': estado_filtro,
            'nombre_filtro': nombre_filtro,
        }
    )