from django.db import models
from datetime import date
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.contrib.auth.models import User
from django.dispatch import receiver
from django.db.models.signals import post_save
import calendar

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
        hoy = date.today()
        return hoy.year - self.fecha_nacimiento.year - (
            (hoy.month, hoy.day) < (self.fecha_nacimiento.month, self.fecha_nacimiento.day)
        )

    def calcular_edad_en_el_anio(self, year=None):
        """
        Edad que cumple en el año (age-at-year-end).
        Ej: si cumple 17 en octubre, en febrero devuelve 17 igual.
        """
        if year is None:
            year = date.today().year
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
    

class Mensualidad(models.Model):
    atleta = models.ForeignKey(Atleta, on_delete=models.CASCADE, related_name='mensualidades')
    mes = models.IntegerField(choices=[(i, calendar.month_name[i]) for i in range(1, 13)])
    año = models.IntegerField(default=date.today().year)
    monto_pagado = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    exonerado = models.BooleanField(default=False)

    class Meta:
        unique_together = ('atleta', 'mes', 'año')
        ordering = ['año', 'mes']

    def estado(self):
        if self.exonerado:
            return "Exonerado"
        elif self.monto_pagado >= 5.00:
            return "Al día"
        else:
            return "Incompleto"

    def __str__(self):
        return f"{self.atleta} - {self.get_mes_display()} {self.año}"

    @property
    def fecha(self):
        return date(self.año, self.mes, 1)


    @receiver(post_save, sender=Atleta)
    def crear_mensualidades_para_nuevo_atleta(sender, instance, created, **kwargs):
        if created:
            año_actual = date.today().year
            for mes in range(1, 13):
                Mensualidad.objects.get_or_create(
                    atleta=instance,
                    año=año_actual,
                    mes=mes,
                    defaults={"monto_pagado": 0.00, "exonerado": False}
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
        today = date.today()
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
    entrenador = models.ForeignKey(Entrenador, on_delete=models.CASCADE)
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

    equipo_local = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='partidos')
    equipo_externo = models.CharField(max_length=100)
    fecha = models.DateField()
    hora = models.TimeField()
    lugar = models.CharField(max_length=150)
    campeonato = models.ForeignKey(Campeonato, on_delete=models.SET_NULL, null=True, blank=True)
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
    partido = models.ForeignKey(Partido, on_delete=models.CASCADE, related_name='estadisticas', null=True, blank=True)
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
        return f"Estadísticas de {self.atleta} - {self.fecha_partido}"
    

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
        today = date.today()
        return today.year - self.fecha_nacimiento.year - (
            (today.month, today.day) < (self.fecha_nacimiento.month, self.fecha_nacimiento.day)
        )