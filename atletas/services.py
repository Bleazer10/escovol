import json

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from django.core.exceptions import ValidationError

from django.contrib.auth.models import User, Group
from django.db import transaction
from django.utils import timezone

from .models import (
    Atleta,
    Entrenador,
    Administrador,
    Mensualidad,
    TarifaMensual,
    TasaCambio,
    Pago,
    PagoMensualidad,
)

# ---- ATLETA ----
@transaction.atomic
def crear_usuario_para_atleta(
    atleta: Atleta,
    username: str,
    password: str,
    email: str = ''
):
    user = User.objects.create_user(
        username=username.strip(),
        email=email,
        password=password
    )

    atleta.user = user
    atleta.save()

    grupo = Group.objects.get(name='Atleta')
    user.groups.add(grupo)

    return user


# ---- ENTRENADOR ----
@transaction.atomic
def crear_usuario_para_entrenador(
    entrenador: Entrenador,
    username: str,
    password: str,
    email: str = ''
):
    user = User.objects.create_user(
        username=username.strip(),
        email=email,
        password=password
    )

    entrenador.user = user
    entrenador.save()

    grupo = Group.objects.get(name='Entrenador')
    user.groups.add(grupo)

    return user


# ---- ADMINISTRADOR ----
@transaction.atomic
def crear_usuario_para_administrador(
    admin: Administrador,
    username: str,
    password: str,
    email: str = ''
):
    user = User.objects.create_user(
        username=username.strip(),
        email=email,
        password=password
    )

    admin.usuario = user
    admin.save()

    grupo = Group.objects.get(name='Administrador')
    user.groups.add(grupo)

    return user

# ---- ELIMINACIÓN SEGURA DE USUARIOS ----
def eliminar_usuario_sin_perfil(user):
    """
    Elimina la cuenta de Django únicamente si ya no está asociada
    a ningún perfil del sistema.
    """
    if not user:
        return

    tiene_otro_perfil = (
        Atleta.objects.filter(user=user).exists()
        or Entrenador.objects.filter(user=user).exists()
        or Administrador.objects.filter(usuario=user).exists()
    )

    if not tiene_otro_perfil:
        user.delete()

# ---- TARIFAS DE MENSUALIDAD ----
def obtener_tarifa_mensual(año, mes):
    """
    Devuelve la tarifa vigente para un mes y año determinados.

    Busca la tarifa cuya fecha de inicio sea la más reciente
    que no supere el período consultado.

    Ejemplos:
        enero 2026      -> $5
        marzo 2026      -> $5
        abril 2026      -> $7
        septiembre 2026 -> $7
    """

    fecha_periodo = date(
        int(año),
        int(mes),
        1
    )

    return (
        TarifaMensual.objects
        .filter(vigente_desde__lte=fecha_periodo)
        .order_by("-vigente_desde")
        .first()
    )

# ---- TASA DE CAMBIO BCV ----

DOLAR_API_URL = "https://ve.dolarapi.com/v1/dolares/oficial"

# Evitamos consultar la API en cada carga de página.
# Durante una hora reutilizamos la última consulta automática.
TASA_CACHE_MINUTOS = 60


class TasaCambioNoDisponible(Exception):
    """
    Se utiliza cuando no fue posible obtener una tasa válida
    desde la fuente externa.
    """
    pass


def consultar_y_guardar_tasa_bcv():
    """
    Consulta la tasa oficial publicada por DolarApi para Venezuela,
    valida la respuesta y guarda la tasa en la base de datos.

    Si para la misma fecha valor ya tenemos exactamente esa tasa,
    reutiliza el registro existente y evita duplicados innecesarios.
    """

    request = Request(
        DOLAR_API_URL,
        headers={
            "User-Agent": "OLYMPO/1.0",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=8) as response:
            contenido = response.read().decode("utf-8")

        datos = json.loads(contenido)

    except (
        HTTPError,
        URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as error:
        raise TasaCambioNoDisponible(
            "No fue posible consultar la tasa BCV."
        ) from error

    try:
        tasa = Decimal(
            str(datos["promedio"])
        ).quantize(
            Decimal("0.000001")
        )

        fecha_actualizacion = datos["fechaActualizacion"]

        fecha_valor = datetime.fromisoformat(
            fecha_actualizacion.replace(
                "Z",
                "+00:00"
            )
        ).date()

    except (
        KeyError,
        TypeError,
        ValueError,
        InvalidOperation,
    ) as error:
        raise TasaCambioNoDisponible(
            "La API devolvió una tasa o fecha inválida."
        ) from error

    if tasa <= 0:
        raise TasaCambioNoDisponible(
            "La API devolvió una tasa no válida."
        )

    # Buscamos la consulta automática más reciente
    # correspondiente a esa misma fecha valor.
    tasa_existente = (
        TasaCambio.objects
        .filter(
            fecha_valor=fecha_valor,
            origen="automatica",
        )
        .order_by("-fecha_consulta")
        .first()
    )

    # Si la tasa oficial no cambió, no llenamos la BD
    # con registros duplicados.
    if (
        tasa_existente
        and tasa_existente.tasa_bs_usd == tasa
    ):
        # Seguimos utilizando el mismo registro para no
        # duplicarlo, pero actualizamos la fecha de consulta.
        #
        # Esto también permite volver de una tasa manual
        # a la automática cuando el administrador pulsa
        # "Actualizar desde BCV".
        TasaCambio.objects.filter(
            pk=tasa_existente.pk
        ).update(
            fecha_consulta=timezone.now()
        )

        tasa_existente.refresh_from_db()

        return tasa_existente

    return TasaCambio.objects.create(
        tasa_bs_usd=tasa,
        fecha_valor=fecha_valor,
        fuente="BCV / DolarApi",
        origen="automatica",
        observacion=(
            "Tasa obtenida automáticamente "
            "desde DolarApi Venezuela."
        ),
    )


def obtener_ultima_tasa_guardada():
    """
    Devuelve la última tasa que fue realmente
    consultada o registrada.

    Esto permite que una tasa manual recién introducida
    tenga prioridad sobre una automática anterior.
    """

    return (
        TasaCambio.objects
        .order_by(
            "-fecha_consulta",
            "-id",
        )
        .first()
    )


def obtener_tasa_actual(forzar_actualizacion=False):
    """
    Devuelve la tasa activa de OLYMPO.

    Reglas:

    - Una tasa manual recién registrada permanece activa.
    - Una tasa automática reciente se reutiliza durante
      el período de caché.
    - Si corresponde consultar la API, se intenta actualizar.
    - Si la API falla durante una carga normal, se utiliza
      la última tasa guardada.
    - Si el administrador pulsa expresamente
      'Actualizar desde BCV' y la API falla, se informa
      del fallo sin sustituir silenciosamente la tasa.
    """

    ultima_tasa = (
        obtener_ultima_tasa_guardada()
    )

    if not forzar_actualizacion:

        # Una tasa manual es una decisión explícita
        # del administrador.
        #
        # Se mantiene activa hasta que se realice
        # correctamente una actualización desde BCV.
        if (
            ultima_tasa
            and ultima_tasa.origen == "manual"
        ):
            return ultima_tasa

        limite_cache = (
            timezone.now()
            - timedelta(
                minutes=TASA_CACHE_MINUTOS
            )
        )

        tasa_reciente = (
            TasaCambio.objects
            .filter(
                origen="automatica",
                fecha_consulta__gte=
                    limite_cache,
            )
            .order_by(
                "-fecha_consulta"
            )
            .first()
        )

        if tasa_reciente:
            return tasa_reciente

    try:

        return consultar_y_guardar_tasa_bcv()

    except TasaCambioNoDisponible:

        # Si el administrador pidió explícitamente
        # una actualización, debemos avisarle que
        # BCV/API no pudo actualizarse.
        if forzar_actualizacion:
            raise

        # En cargas normales del sistema seguimos
        # funcionando con la última tasa conocida.
        if ultima_tasa:
            return ultima_tasa

        raise

# ---- REGISTRO Y DISTRIBUCIÓN DE PAGOS ----

def _convertir_monto_positivo(valor, nombre_campo="monto"):
    """
    Convierte un valor monetario a Decimal con dos decimales
    y comprueba que sea mayor que cero.
    """

    try:
        monto = Decimal(
            str(valor)
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as error:
        raise ValidationError(
            f"El {nombre_campo} ingresado no es válido."
        ) from error

    if monto <= 0:
        raise ValidationError(
            f"El {nombre_campo} debe ser mayor que cero."
        )

    return monto


def _saldo_real_mensualidad(mensualidad):
    """
    Devuelve cuánto falta realmente para completar
    la cuota nominal de una mensualidad.

    Si ya está administrativamente al día por tolerancia,
    devuelve cero.
    """

    if mensualidad.exonerado:
        return Decimal("0.0000")

    if mensualidad.estado_codigo == "al_dia":
        return Decimal("0.0000")

    cuota = mensualidad.cuota_usd

    if cuota is None:
        raise ValidationError(
            (
                "No existe una tarifa configurada para "
                f"{mensualidad.mes}/{mensualidad.año}."
            )
        )

    saldo = max(
        Decimal("0.00"),
        Decimal(str(cuota))
        - mensualidad.total_pagado_usd
    )

    return saldo.quantize(
        Decimal("0.0001"),
        rounding=ROUND_HALF_UP,
    )


@transaction.atomic
def registrar_pago(
    *,
    atleta,
    mensualidades,
    moneda,
    monto_total,
    usuario=None,
    metodo="",
    referencia="",
    observacion="",
    fecha_pago=None,
    tasa_cambio=None,
):
    """
    Registra una transacción real y distribuye su equivalente
    en USD entre una o varias mensualidades.

    La distribución se hace comenzando por el período más antiguo
    de los seleccionados.

    Ejemplo:

        Julio       $7
        Agosto      $7
        Septiembre  $7
        Octubre     $7

        Pago equivalente: $28

    Resultado:

        Julio       $7
        Agosto      $7
        Septiembre  $7
        Octubre     $7

    Si se pagan $20:

        Julio       $7
        Agosto      $7
        Septiembre  $6
        Octubre     pendiente

    Si existen unos céntimos adicionales, se aplican al último
    período alcanzado por la transacción.
    """

    if not atleta or not atleta.pk:
        raise ValidationError(
            "Debe seleccionarse un atleta válido."
        )

    moneda = str(moneda).strip().upper()

    if moneda not in {"USD", "VES"}:
        raise ValidationError(
            "La moneda debe ser USD o VES."
        )

    monto_decimal = _convertir_monto_positivo(
        monto_total,
        "monto del pago"
    )

    # -----------------------------------------
    # NORMALIZAR LAS MENSUALIDADES SELECCIONADAS
    # -----------------------------------------

    ids_mensualidades = []

    for item in mensualidades:
        mensualidad_id = getattr(
            item,
            "pk",
            item
        )

        if mensualidad_id is None:
            raise ValidationError(
                "Se recibió una mensualidad sin guardar."
            )

        try:
            mensualidad_id = int(mensualidad_id)
        except (TypeError, ValueError) as error:
            raise ValidationError(
                "Se recibió una mensualidad inválida."
            ) from error

        ids_mensualidades.append(
            mensualidad_id
        )

    if not ids_mensualidades:
        raise ValidationError(
            "Debe seleccionarse al menos una mensualidad."
        )

    if len(ids_mensualidades) != len(
        set(ids_mensualidades)
    ):
        raise ValidationError(
            "No se puede seleccionar dos veces "
            "la misma mensualidad."
        )

    mensualidades_bd = list(
        Mensualidad.objects
        .select_for_update()
        .filter(
            id__in=ids_mensualidades
        )
        .order_by(
            "año",
            "mes",
            "id",
        )
    )

    if len(mensualidades_bd) != len(
        ids_mensualidades
    ):
        raise ValidationError(
            "Una o más mensualidades seleccionadas "
            "no existen."
        )

    # Todas deben pertenecer al mismo atleta.
    for mensualidad in mensualidades_bd:

        if mensualidad.atleta_id != atleta.id:
            raise ValidationError(
                "Todas las mensualidades deben pertenecer "
                "al atleta seleccionado."
            )

        if mensualidad.exonerado:
            raise ValidationError(
                (
                    f"La mensualidad {mensualidad.mes}/"
                    f"{mensualidad.año} está exonerada "
                    "y no necesita un pago."
                )
            )

        if mensualidad.tarifa_aplicable is None:
            raise ValidationError(
                (
                    "No existe una tarifa configurada para "
                    f"{mensualidad.mes}/{mensualidad.año}."
                )
            )

    # -----------------------------------------
    # CALCULAR EQUIVALENTE USD
    # -----------------------------------------

    if moneda == "USD":

        equivalente_usd = monto_decimal.quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP,
        )

        tasa_usada = None
        fecha_tasa = None
        fuente_tasa = ""

    else:

        if tasa_cambio is None:
            tasa_cambio = obtener_tasa_actual()

        tasa_usada = tasa_cambio.tasa_bs_usd

        if (
            tasa_usada is None
            or tasa_usada <= 0
        ):
            raise ValidationError(
                "La tasa de cambio disponible no es válida."
            )

        equivalente_usd = (
            monto_decimal / tasa_usada
        ).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP,
        )

        fecha_tasa = tasa_cambio.fecha_valor
        fuente_tasa = tasa_cambio.fuente

    # -----------------------------------------
    # CALCULAR LA DISTRIBUCIÓN
    # -----------------------------------------

    restante = equivalente_usd
    distribucion = []

    for mensualidad in mensualidades_bd:

        if restante <= Decimal("0.0000"):
            break

        saldo = _saldo_real_mensualidad(
            mensualidad
        )

        if saldo <= Decimal("0.0000"):
            continue

        monto_aplicar = min(
            restante,
            saldo
        )

        monto_aplicar = monto_aplicar.quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP,
        )

        distribucion.append(
            [
                mensualidad,
                monto_aplicar,
            ]
        )

        restante = (
            restante - monto_aplicar
        ).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP,
        )

    if not distribucion:
        raise ValidationError(
            "Las mensualidades seleccionadas ya están "
            "pagadas o no admiten pagos."
        )

    # Si hay un pequeño excedente, lo asociamos
    # al último período alcanzado.
    #
    # De esta forma toda la transacción queda aplicada
    # y no dejamos dinero sin identificar.
    if restante > Decimal("0.0000"):

        distribucion[-1][1] = (
            distribucion[-1][1]
            + restante
        ).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP,
        )

        restante = Decimal("0.0000")

    # -----------------------------------------
    # CREAR LA TRANSACCIÓN
    # -----------------------------------------

    pago = Pago(
        atleta=atleta,
        moneda=moneda,
        monto_total=monto_decimal,
        equivalente_usd=equivalente_usd,
        tasa_bs_usd=tasa_usada,
        fecha_tasa=fecha_tasa,
        fuente_tasa=fuente_tasa,
        fecha_pago=(
            fecha_pago
            if fecha_pago is not None
            else timezone.localdate()
        ),
        metodo=str(metodo).strip(),
        referencia=str(referencia).strip(),
        observacion=str(observacion).strip(),
        registrado_por=(
            usuario
            if usuario is not None
            and getattr(
                usuario,
                "is_authenticated",
                False
            )
            else None
        ),
    )

    pago.full_clean()
    pago.save()

    # -----------------------------------------
    # CREAR LAS APLICACIONES A CADA MES
    # -----------------------------------------

    for mensualidad, monto_aplicado in distribucion:

        aplicacion = PagoMensualidad(
            pago=pago,
            mensualidad=mensualidad,
            monto_aplicado_usd=monto_aplicado,
        )

        aplicacion.full_clean()
        aplicacion.save()

        if not mensualidad.en_control:

            Mensualidad.objects.filter(
                pk=mensualidad.pk
            ).update(
                en_control=True
            )

            mensualidad.en_control = True

    return pago

@transaction.atomic
def anular_pago(
    pago,
    usuario,
    motivo,
):
    """
    Anula una transacción de pago sin eliminarla.

    El pago permanece en el historial, pero al pasar
    a estado 'anulado' deja de afectar:

    - mensualidades;
    - saldos;
    - estados;
    - recaudación.

    El motivo es obligatorio.
    """

    if pago is None or not getattr(
        pago,
        "pk",
        None,
    ):
        raise ValidationError(
            "El pago indicado no es válido."
        )

    motivo = str(
        motivo or ""
    ).strip()

    if not motivo:
        raise ValidationError(
            "Debe indicar el motivo de la anulación."
        )

    pago_bloqueado = (
        Pago.objects
        .select_for_update()
        .get(
            pk=pago.pk
        )
    )

    if pago_bloqueado.estado == "anulado":
        raise ValidationError(
            "Este pago ya se encuentra anulado."
        )

    pago_bloqueado.estado = "anulado"

    pago_bloqueado.anulado_en = (
        timezone.now()
    )

    if (
        usuario
        and getattr(
            usuario,
            "is_authenticated",
            False,
        )
    ):
        pago_bloqueado.anulado_por = usuario
    else:
        pago_bloqueado.anulado_por = None

    pago_bloqueado.motivo_anulacion = motivo

    pago_bloqueado.full_clean()

    pago_bloqueado.save(
        update_fields=[
            "estado",
            "anulado_en",
            "anulado_por",
            "motivo_anulacion",
        ]
    )

    return pago_bloqueado

@transaction.atomic
def exonerar_mensualidad(
    mensualidad,
    usuario,
    motivo,
):
    """
    Exonera una mensualidad sin eliminar información.

    Reglas:
    - El motivo es obligatorio.
    - No puede exonerarse un mes que ya esté exonerado.
    - No puede exonerarse un mes que tenga dinero pagado
      mediante el sistema anterior.
    - No puede exonerarse un mes con pagos ACTIVOS.
    """

    if mensualidad is None or not getattr(
        mensualidad,
        "pk",
        None,
    ):
        raise ValidationError(
            "La mensualidad indicada no es válida."
        )

    motivo = str(
        motivo or ""
    ).strip()

    if not motivo:
        raise ValidationError(
            "Debe indicar el motivo de la exoneración."
        )

    mensualidad_bloqueada = (
        Mensualidad.objects
        .select_for_update()
        .get(
            pk=mensualidad.pk
        )
    )

    if mensualidad_bloqueada.exonerado:
        raise ValidationError(
            "Esta mensualidad ya se encuentra exonerada."
        )

    # -----------------------------------------
    # PAGOS DEL SISTEMA ANTERIOR
    # -----------------------------------------

    monto_anterior = Decimal(
        str(
            mensualidad_bloqueada.monto_pagado
            or Decimal("0.00")
        )
    )

    if monto_anterior > Decimal("0.00"):
        raise ValidationError(
            (
                "No puede exonerarse esta mensualidad "
                "porque ya contiene un pago registrado."
            )
        )

    # -----------------------------------------
    # PAGOS DEL NUEVO SISTEMA
    # -----------------------------------------

    tiene_pago_activo = (
        mensualidad_bloqueada.pagos
        .filter(
            pago__estado="activo"
        )
        .exists()
    )

    if tiene_pago_activo:
        raise ValidationError(
            (
                "No puede exonerarse esta mensualidad "
                "porque tiene uno o más pagos activos. "
                "Primero debe anular el pago correspondiente."
            )
        )

    mensualidad_bloqueada.en_control = True
    mensualidad_bloqueada.exonerado = True
    mensualidad_bloqueada.exonerado_en = (
        timezone.now()
    )

    if (
        usuario
        and getattr(
            usuario,
            "is_authenticated",
            False,
        )
    ):
        mensualidad_bloqueada.exonerado_por = (
            usuario
        )
    else:
        mensualidad_bloqueada.exonerado_por = None

    mensualidad_bloqueada.motivo_exoneracion = (
        motivo
    )

    mensualidad_bloqueada.full_clean()

    mensualidad_bloqueada.save(
        update_fields=[
            "en_control",
            "exonerado",
            "exonerado_en",
            "exonerado_por",
            "motivo_exoneracion",
        ]
    )

    return mensualidad_bloqueada


@transaction.atomic
def quitar_exoneracion(
    mensualidad,
):
    """
    Retira la exoneración de una mensualidad.

    Al hacerlo, el estado vuelve a calcularse utilizando
    normalmente su tarifa y sus pagos válidos.
    """

    if mensualidad is None or not getattr(
        mensualidad,
        "pk",
        None,
    ):
        raise ValidationError(
            "La mensualidad indicada no es válida."
        )

    mensualidad_bloqueada = (
        Mensualidad.objects
        .select_for_update()
        .get(
            pk=mensualidad.pk
        )
    )

    if not mensualidad_bloqueada.exonerado:
        raise ValidationError(
            "Esta mensualidad no se encuentra exonerada."
        )

    mensualidad_bloqueada.exonerado = False
    mensualidad_bloqueada.exonerado_en = None
    mensualidad_bloqueada.exonerado_por = None
    mensualidad_bloqueada.motivo_exoneracion = ""

    mensualidad_bloqueada.full_clean()

    mensualidad_bloqueada.save(
        update_fields=[
            "exonerado",
            "exonerado_en",
            "exonerado_por",
            "motivo_exoneracion",
        ]
    )

    return mensualidad_bloqueada