from django.db import models
from datetime import date
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Sum
from decimal import Decimal
from django.contrib.auth.models import User
import calendar
from django.utils.formats import date_format

class Atleta(models.Model):

    SEXO = (
    ('masculino', 'Masculino'),
    ('femenino', 'Femenino'),
    )

    TURNOS = (
        ('T1', 'Turno 1'),
        ('T2', 'Turno 2'),
        ('T3', 'Turno 3'),
    )

    POSICIONES = (
        ('Por definir', 'Por definir'),
        ('colocador', 'Colocador'),
        ('opuesto', 'Opuesto'),
        ('central', 'Central'),
        ('libero', 'Libero'),
        ('punta', 'Punta'),
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)  # <— NUEVO
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    fecha_nacimiento = models.DateField()
    sexo = models.CharField(max_length=10, choices=SEXO)
    categoria = models.CharField(max_length=10, blank=True)

    turno = models.CharField(max_length=10, choices=TURNOS)
    posicion = models.CharField(max_length=50, choices=POSICIONES)

    cedula = models.CharField(max_length=20, unique=True)
    telefono = models.CharField(max_length=20)
    direccion = models.TextField(blank=True)
    numero_camisa = models.PositiveIntegerField(null=True, blank=True)

    fecha_registro = models.DateTimeField(auto_now_add=True)

    salto = models.FloatField(null=True, blank=True, help_text="Salto en metros")
    alcance = models.FloatField(null=True, blank=True, help_text="Alcance en metros")
    peso = models.FloatField(null=True, blank=True, help_text="Peso en kilogramos")
    estatura = models.FloatField(null=True, blank=True, help_text="Estatura en metros")

        # ==== Representante (solo si menor de edad) ====
    representante_nombre = models.CharField(max_length=100, blank=True, null=True)
    representante_apellido = models.CharField(max_length=100, blank=True, null=True)
    representante_cedula = models.CharField(max_length=20, blank=True, null=True)
    representante_telefono = models.CharField(max_length=20, blank=True, null=True)

    def calcular_edad(self):
        hoy = timezone.localdate()
        return hoy.year - self.fecha_nacimiento.year - (
            (hoy.month, hoy.day) < (self.fecha_nacimiento.month, self.fecha_nacimiento.day)
        )

    def calcular_edad_en_el_anio(self, year=None):
        """
        Edad que cumple en el año (age-at-year-end).
        Ej: si cumple 17 en octubre, en febrero devuelve 17 igual.
        """
        if year is None:
            year = timezone.localdate().year
        return year - self.fecha_nacimiento.year

    def get_categoria(self):
        edad = self.calcular_edad_en_el_anio()
        if edad < 9: return "U9"
        elif edad < 11: return "U11"
        elif edad < 13: return "U13"
        elif edad < 15: return "U15"
        elif edad < 17: return "U17"
        elif edad < 19: return "U19"
        elif edad < 21: return "U21"
        elif edad < 23: return "U23"
        else: return "Libre"

    def save(self, *args, **kwargs):
            self.categoria = self.get_categoria()
            super().save(*args, **kwargs)

    @property
    def despegue(self):
        if self.salto is not None and self.alcance is not None:
            return round((self.salto - self.alcance) * 100, 2)  # en cm
        return None

    def __str__(self):
        return f"{self.nombre} {self.apellido} ({self.get_categoria()})"


def anio_actual():
    return timezone.localdate().year


class Mensualidad(models.Model):
    atleta = models.ForeignKey(Atleta, on_delete=models.CASCADE, related_name='mensualidades')
    mes = models.IntegerField(choices=[(i, calendar.month_name[i]) for i in range(1, 13)])
    año = models.IntegerField(default=anio_actual)
    monto_pagado = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    exonerado = models.BooleanField(default=False)
    exonerado_en = models.DateTimeField(
        null=True,
        blank=True
    )

    exonerado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mensualidades_exoneradas"
    )

    motivo_exoneracion = models.TextField(
        blank=True
    )

    en_control = models.BooleanField(
        default=False,
        help_text=(
            "Indica si este período forma parte "
            "del control real de mensualidades."
        )
    )

    class Meta:
        unique_together = ('atleta', 'mes', 'año')
        ordering = ['año', 'mes']

    @property
    def tarifa_aplicable(self):
        """
        Devuelve la tarifa histórica correspondiente
        al mes y año de esta mensualidad.
        """

        # Import local para evitar dependencia circular.
        from .services import obtener_tarifa_mensual

        return obtener_tarifa_mensual(
            self.año,
            self.mes
        )


    @property
    def cuota_usd(self):
        """
        Monto oficial de la mensualidad para este período.
        """

        tarifa = self.tarifa_aplicable

        if not tarifa:
            return None

        return tarifa.monto_usd


    @property
    def tolerancia_usd(self):
        """
        Tolerancia permitida para considerar la mensualidad
        como pagada.
        """

        tarifa = self.tarifa_aplicable

        if not tarifa:
            return Decimal("0.00")

        return tarifa.tolerancia_usd


    @property
    def total_pagado_usd(self):
        """
        Total pagado expresado en USD.

        Durante la transición suma:
        - monto_pagado del sistema anterior;
        - aplicaciones pertenecientes a pagos ACTIVOS.

        Los pagos anulados permanecen en el historial,
        pero dejan de afectar el total de la mensualidad.
        """

        total_anterior = Decimal(
            str(
                self.monto_pagado
                if self.monto_pagado is not None
                else Decimal("0.00")
            )
        )

        total_nuevo = Decimal("0.00")

        if self.pk:

            cache_prefetch = getattr(
                self,
                "_prefetched_objects_cache",
                {}
            )

            if "pagos" in cache_prefetch:

                total_nuevo = sum(
                    (
                        Decimal(
                            str(
                                aplicacion.monto_aplicado_usd
                            )
                        )
                        for aplicacion
                        in cache_prefetch["pagos"]
                        if (
                            aplicacion.pago_id
                            and aplicacion.pago.estado == "activo"
                        )
                    ),
                    Decimal("0.00"),
                )

            else:

                agregado = (
                    self.pagos
                    .filter(
                        pago__estado="activo"
                    )
                    .aggregate(
                        total=Sum(
                            "monto_aplicado_usd"
                        )
                    )["total"]
                )

                if agregado is not None:
                    total_nuevo = Decimal(
                        str(agregado)
                    )

        return (
            total_anterior
            + total_nuevo
        ).quantize(
            Decimal("0.0001")
        )


    @property
    def estado_codigo(self):
        """
        Estado interno de la mensualidad.

        Un período que todavía no forma parte del control real
        y no tiene pagos registrados se considera "sin_registro",
        no una deuda.
        """

        if self.exonerado:
            return "exonerado"

        tarifa = self.tarifa_aplicable

        if tarifa is None:
            return "sin_tarifa"

        total_pagado = self.total_pagado_usd

        # -----------------------------------------
        # PERÍODO AÚN NO INCORPORADO AL CONTROL
        # -----------------------------------------

        if (
            not self.en_control
            and total_pagado <= Decimal("0.00")
        ):
            return "sin_registro"

        limite_al_dia = max(
            Decimal("0.00"),
            Decimal(str(tarifa.monto_usd))
            - Decimal(str(tarifa.tolerancia_usd)),
        )

        if total_pagado >= limite_al_dia:
            return "al_dia"

        if total_pagado > Decimal("0.00"):
            return "parcial"

        return "pendiente"


    @property
    def saldo_pendiente_usd(self):
        """
        Saldo pendiente del período.

        Los meses sin registro todavía no generan deuda.
        """

        tarifa = self.tarifa_aplicable

        if tarifa is None:
            return None

        if self.exonerado:
            return Decimal("0.00")

        if self.estado_codigo == "sin_registro":
            return None

        total_pagado = self.total_pagado_usd

        limite_al_dia = max(
            Decimal("0.00"),
            Decimal(str(tarifa.monto_usd))
            - Decimal(str(tarifa.tolerancia_usd)),
        )

        if total_pagado >= limite_al_dia:
            return Decimal("0.00")

        saldo = max(
            Decimal("0.00"),
            Decimal(str(tarifa.monto_usd))
            - total_pagado,
        )

        return saldo.quantize(
            Decimal("0.01")
        )

    def estado(self):
        estados = {
            "al_dia": "Al día",
            "parcial": "Parcial",
            "pendiente": "Pendiente",
            "exonerado": "Exonerado",
            "sin_tarifa": "Sin tarifa",
            "sin_registro": "Sin registro",
        }

        return estados.get(
            self.estado_codigo,
            "Sin registro"
        )

    def __str__(self):
        nombre_mes = date_format(self.fecha, 'F')
        return f"{self.atleta} - {nombre_mes} {self.año}"

    @property
    def fecha(self):
        return date(self.año, self.mes, 1)

class TarifaMensual(models.Model):
    """
    Define cuánto cuesta la mensualidad a partir de un período determinado.

    Permite conservar el histórico:
    por ejemplo, una tarifa de $7 desde septiembre de 2026
    y una futura tarifa de $8 desde enero de 2027.
    """

    monto_usd = models.DecimalField(
        max_digits=8,
        decimal_places=2
    )

    tolerancia_usd = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.10")
    )

    vigente_desde = models.DateField(
        unique=True,
        help_text="Se almacenará como el primer día del mes."
    )

    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-vigente_desde"]
        verbose_name = "Tarifa mensual"
        verbose_name_plural = "Tarifas mensuales"

    def save(self, *args, **kwargs):
        if self.vigente_desde:
            self.vigente_desde = self.vigente_desde.replace(day=1)

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"${self.monto_usd} desde "
            f"{self.vigente_desde.strftime('%m/%Y')}"
        )


class TasaCambio(models.Model):
    """
    Guarda las tasas Bs/USD obtenidas automáticamente o
    registradas manualmente.

    Esto nos permite conservar un histórico de las tasas utilizadas.
    """

    ORIGEN_CHOICES = [
        ("automatica", "Automática"),
        ("manual", "Manual"),
    ]

    tasa_bs_usd = models.DecimalField(
        max_digits=14,
        decimal_places=6
    )

    fecha_valor = models.DateField()

    fuente = models.CharField(
        max_length=50,
        default="BCV"
    )

    origen = models.CharField(
        max_length=20,
        choices=ORIGEN_CHOICES,
        default="automatica"
    )

    fecha_consulta = models.DateTimeField(
        auto_now_add=True
    )

    observacion = models.CharField(
        max_length=255,
        blank=True
    )

    class Meta:
        ordering = [
            "-fecha_valor",
            "-fecha_consulta",
        ]

        verbose_name = "Tasa de cambio"
        verbose_name_plural = "Tasas de cambio"

    def __str__(self):
        return (
            f"Bs {self.tasa_bs_usd} / USD "
            f"({self.fecha_valor.strftime('%d/%m/%Y')})"
        )

class Pago(models.Model):
    """
    Representa una transacción real realizada por un atleta.

    Una sola transacción puede cancelar una o varias mensualidades.
    """

    MONEDA_CHOICES = [
        ("VES", "Bolívares"),
        ("USD", "Dólares"),
    ]

    METODO_CHOICES = [
        ("pago_movil", "Pago móvil"),
        ("transferencia", "Transferencia"),
        ("efectivo", "Efectivo"),
        ("zelle", "Zelle"),
        ("otro", "Otro"),
    ]

    ESTADO_CHOICES = [
        ("activo", "Activo"),
        ("anulado", "Anulado"),
    ]

    atleta = models.ForeignKey(
        Atleta,
        on_delete=models.PROTECT,
        related_name="pagos"
    )

    moneda = models.CharField(
        max_length=3,
        choices=MONEDA_CHOICES
    )

    monto_total = models.DecimalField(
        max_digits=16,
        decimal_places=2
    )

    equivalente_usd = models.DecimalField(
        max_digits=12,
        decimal_places=4
    )

    tasa_bs_usd = models.DecimalField(
        max_digits=14,
        decimal_places=6,
        null=True,
        blank=True
    )

    fecha_tasa = models.DateField(
        null=True,
        blank=True
    )

    fuente_tasa = models.CharField(
        max_length=50,
        blank=True
    )

    fecha_pago = models.DateField(
        default=timezone.localdate
    )

    metodo = models.CharField(
        max_length=20,
        choices=METODO_CHOICES,
        blank=True
    )

    referencia = models.CharField(
        max_length=100,
        blank=True
    )

    observacion = models.TextField(
        blank=True
    )

    registrado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_registrados"
    )

    creado_en = models.DateTimeField(
        auto_now_add=True
    )

    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default="activo"
    )

    anulado_en = models.DateTimeField(
        null=True,
        blank=True
    )

    anulado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_anulados"
    )

    motivo_anulacion = models.TextField(
        blank=True
    )

    class Meta:
        ordering = [
            "-fecha_pago",
            "-creado_en",
        ]

        verbose_name = "Pago"
        verbose_name_plural = "Pagos"

    def __str__(self):
        return (
            f"{self.atleta} - "
            f"{self.monto_total} {self.moneda} - "
            f"{self.fecha_pago.strftime('%d/%m/%Y')}"
        )

    @property
    def total_aplicado_usd(self):
        """
        Total del pago que ya fue distribuido
        entre mensualidades.
        """

        total = self.aplicaciones.aggregate(
            total=Sum("monto_aplicado_usd")
        )["total"]

        if total is None:
            return Decimal("0.0000")

        return Decimal(
            str(total)
        ).quantize(
            Decimal("0.0001")
        )


    @property
    def saldo_sin_aplicar_usd(self):
        """
        Diferencia entre el equivalente real de la
        transacción y lo distribuido entre mensualidades.
        """

        return (
            self.equivalente_usd
            - self.total_aplicado_usd
        ).quantize(
            Decimal("0.0001")
        )

class PagoMensualidad(models.Model):
    """
    Representa cuánto de una transacción de pago
    fue aplicado a una mensualidad específica.

    Una misma transacción puede aplicarse a
    uno o varios meses.
    """

    pago = models.ForeignKey(
        Pago,
        on_delete=models.CASCADE,
        related_name="aplicaciones",
        null=True,
        blank=True,
    )

    mensualidad = models.ForeignKey(
        Mensualidad,
        on_delete=models.CASCADE,
        related_name="pagos"
    )

    monto_aplicado_usd = models.DecimalField(
        max_digits=12,
        decimal_places=4
    )

    creado_en = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = [
            "id",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "pago",
                    "mensualidad",
                ],
                name="pago_unico_por_mensualidad"
            )
        ]

        verbose_name = "Aplicación de pago"
        verbose_name_plural = "Aplicaciones de pagos"

    def clean(self):
        super().clean()

        if (
            self.monto_aplicado_usd is not None
            and self.monto_aplicado_usd <= Decimal("0.00")
        ):
            raise ValidationError(
                {
                    "monto_aplicado_usd":
                        "El monto aplicado debe ser mayor que cero."
                }
            )

        # Un pago solamente puede aplicarse
        # a mensualidades del mismo atleta.
        if (
            self.pago_id
            and self.mensualidad_id
            and self.pago.atleta_id
            != self.mensualidad.atleta_id
        ):
            raise ValidationError(
                "La mensualidad seleccionada no pertenece "
                "al atleta de este pago."
            )

    def __str__(self):
        return (
            f"{self.mensualidad} - "
            f"${self.monto_aplicado_usd}"
        )

class Entrenador(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)  # <— NUEVO
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    cedula = models.CharField(max_length=20, unique=True)
    fecha_nacimiento = models.DateField()
    telefono = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.nombre} {self.apellido}"

    @property
    def edad(self):
        today = timezone.localdate()
        return today.year - self.fecha_nacimiento.year - (
            (today.month, today.day) < (self.fecha_nacimiento.month, self.fecha_nacimiento.day)
            )

class Campeonato(models.Model):
    TIPO_CHOICES = [
        ('formal', 'Formal'),
        ('amistoso', 'Amistoso'),
    ]

    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    anio = models.PositiveIntegerField()
    fecha_inicio = models.DateField(blank=True, null=True)
    descripcion = models.TextField(blank=True)

    def __str__(self):
        return f"{self.nombre} - {self.anio}"

class Equipo(models.Model):
    SEXO_CHOICES = [
        ('masculino', 'Masculino'),
        ('femenino', 'Femenino'),
        ('mixto', 'Mixto'),
    ]
    nombre = models.CharField(max_length=100)
    entrenador = models.ForeignKey(Entrenador, on_delete=models.PROTECT)
    atletas = models.ManyToManyField(Atleta)
    categoria = models.CharField(max_length=50)
    sexo_equipo = models.CharField(max_length=10, choices=SEXO_CHOICES, null=True, blank=True)
    edad_tope = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return self.nombre


class Partido(models.Model):
    ESTADOS = [
        ('programado', 'Programado'),
        ('en_curso', 'En curso'),
        ('finalizado', 'Finalizado'),
        ('cancelado', 'Cancelado'),
    ]

    FORMATOS = [
        ('3-2', 'Ganar 2 de 3 sets'),
        ('5-3', 'Ganar 3 de 5 sets'),
    ]

    equipo_local = models.ForeignKey(Equipo, on_delete=models.PROTECT, related_name='partidos')
    equipo_externo = models.CharField(max_length=100)
    fecha = models.DateField()
    hora = models.TimeField()
    lugar = models.CharField(max_length=150)
    campeonato = models.ForeignKey(Campeonato, on_delete=models.PROTECT, null=True, blank=True)
    observaciones = models.TextField(blank=True, null=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='programado')
    formato_partido = models.CharField(max_length=5, choices=FORMATOS, default='5-3')
    ganador = models.CharField(max_length=20, choices=[('local', 'Equipo Local'), ('externo', 'Equipo Externo')], null=True, blank=True)


    # Resultado por sets
    set1_local = models.PositiveIntegerField(null=True, blank=True)
    set1_externo = models.PositiveIntegerField(null=True, blank=True)
    set2_local = models.PositiveIntegerField(null=True, blank=True)
    set2_externo = models.PositiveIntegerField(null=True, blank=True)
    set3_local = models.PositiveIntegerField(null=True, blank=True)
    set3_externo = models.PositiveIntegerField(null=True, blank=True)
    set4_local = models.PositiveIntegerField(null=True, blank=True)
    set4_externo = models.PositiveIntegerField(null=True, blank=True)
    set5_local = models.PositiveIntegerField(null=True, blank=True)
    set5_externo = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.equipo_local.nombre} vs {self.equipo_externo} - {self.fecha}"

    def resultado_final(self):
        sets_local = 0
        sets_externo = 0
        for i in range(1, 6):
            local = getattr(self, f"set{i}_local")
            externo = getattr(self, f"set{i}_externo")
            if local is not None and externo is not None:
                if local > externo:
                    sets_local += 1
                elif externo > local:
                    sets_externo += 1
        return f"{sets_local} - {sets_externo}"

    @property
    def resultado_con_nombre(self):
        if self.estado != 'finalizado':
            return None

        resultado = self.resultado_final()
        if self.ganador == 'local':
            return f"{self.equipo_local.nombre} {resultado}"
        elif self.ganador == 'externo':
            return f"{self.equipo_externo} {resultado}"
        return "—"

class Estadistica(models.Model):
    atleta = models.ForeignKey(Atleta, on_delete=models.CASCADE, related_name='estadisticas')
    partido = models.ForeignKey(Partido, on_delete=models.PROTECT, related_name='estadisticas', null=True, blank=True)
    puntos = models.PositiveIntegerField(default=0)
    saques = models.PositiveIntegerField(default=0)
    remates = models.PositiveIntegerField(default=0)
    bloqueos = models.PositiveIntegerField(default=0)
    armadas = models.PositiveIntegerField(default=0)
    recepciones = models.PositiveIntegerField(default=0)
    errores = models.PositiveIntegerField(default=0)
    alcance = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    salto = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)


    def __str__(self):
        if self.partido:
            return f"Estadísticas de {self.atleta} - {self.partido.fecha}"
        return f"Estadísticas de {self.atleta}"


class Administrador(models.Model):
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name="administrador")
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    cedula = models.CharField(max_length=20, unique=True)
    fecha_nacimiento = models.DateField()
    telefono = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return f"{self.nombre} {self.apellido}"

    @property
    def edad(self):
        today = timezone.localdate()
        return today.year - self.fecha_nacimiento.year - (
            (today.month, today.day) < (self.fecha_nacimiento.month, self.fecha_nacimiento.day)
        )
