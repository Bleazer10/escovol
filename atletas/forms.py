from django import forms
from .models import Estadistica, Entrenador, Atleta, Campeonato, Partido, Equipo, Administrador
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class AtletaForm(forms.ModelForm):
    class Meta:
        model = Atleta
        fields = [
            'nombre',
            'apellido',
            'fecha_nacimiento',
            'sexo',
            'cedula',
            'telefono',
            'direccion',  # NUEVO
            'numero_camisa',
            'posicion',
            'turno',
            'salto', 
            'alcance',
            'peso', 
            'estatura',

            # Campos del representante
            'representante_nombre',
            'representante_apellido',
            'representante_cedula',
            'representante_telefono',
        ]

        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'apellido': forms.TextInput(attrs={'class': 'form-control'}),
            'fecha_nacimiento': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'sexo': forms.Select(choices=Atleta._meta.get_field('sexo').choices, attrs={'class': 'form-select'}),
            'cedula': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Ej: Av. Principal, Casa 45, Maracay'
            }),
            'numero_camisa': forms.NumberInput(attrs={'class': 'form-control'}),
            'posicion': forms.Select(choices=Atleta._meta.get_field('posicion').choices, attrs={'class': 'form-select'}),
            'turno': forms.Select(choices=Atleta._meta.get_field('turno').choices, attrs={'class': 'form-select'}),

            'salto': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Ej: 2.85',
                'title': 'Salto en metros'
            }),
            'alcance': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Ej: 2.45',
                'title': 'Alcance en metros'
            }),
            'peso': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.1',
                'placeholder': 'Ej: 65.5'
            }),
            'estatura': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Ej: 1.75'
            }),

            # Widgets para representante
            'representante_nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'representante_apellido': forms.TextInput(attrs={'class': 'form-control'}),
            'representante_cedula': forms.TextInput(attrs={'class': 'form-control'}),
            'representante_telefono': forms.TextInput(attrs={'class': 'form-control'}),
        }

class UsuarioForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        required=False,
        label="Nueva Contraseña"
    )

    is_active = forms.ChoiceField(
        choices=[("True", "Activo"), ("False", "Inactivo")],
        label="Estado"
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'is_active']  # ⚠️ Quitamos password de aquí

    def clean_is_active(self):
        value = self.cleaned_data['is_active']
        return value == "True"

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")

        # Solo se actualiza si el admin escribió una nueva clave
        if password:
            user.set_password(password)

        if commit:
            user.save()
        return user


class EntrenadorForm(forms.ModelForm):
    class Meta:
        model = Entrenador
        fields = ['nombre', 'apellido', 'cedula', 'fecha_nacimiento', 'telefono']
        widgets = {
            'fecha_nacimiento': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
            })
        }

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.get('instance')
        super().__init__(*args, **kwargs)

    def clean_cedula(self):
        cedula = self.cleaned_data.get('cedula')
        if Entrenador.objects.exclude(id=self.instance.id).filter(cedula=cedula).exists():
            raise forms.ValidationError("Ya existe un entrenador con esta cédula.")
        return cedula

class CampeonatoForm(forms.ModelForm):
    class Meta:
        model = Campeonato
        fields = ['nombre', 'tipo', 'anio', 'fecha_inicio', 'descripcion']
        widgets = {
            'fecha_inicio': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'anio': forms.NumberInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

# forms.py
class EquipoForm(forms.ModelForm):
    class Meta:
        model = Equipo
        fields = ['nombre', 'entrenador', 'categoria', 'sexo_equipo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'entrenador': forms.Select(attrs={'class': 'form-select'}),
            'categoria': forms.TextInput(attrs={'class': 'form-control'}),
            'sexo_equipo': forms.Select(attrs={'class': 'form-select'}),
        }

class PartidoForm(forms.ModelForm):
    class Meta:
        model = Partido
        fields = [
            'equipo_local',
            'equipo_externo',
            'fecha',
            'hora',
            'lugar',
            'campeonato',
            'estado',
            'formato_partido',
            'observaciones',
            'set1_local', 'set1_externo',
            'set2_local', 'set2_externo',
            'set3_local', 'set3_externo',
            'set4_local', 'set4_externo',
            'set5_local', 'set5_externo',
        ]
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'hora': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
            'campeonato': forms.Select(attrs={'class': 'form-select'}),
            'formato_partido': forms.Select(attrs={'class': 'form-select'}),
            'observaciones': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'equipo_local': forms.Select(attrs={'class': 'form-select'}),
            'equipo_externo': forms.TextInput(attrs={'class': 'form-control'}),
            'lugar': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        errores = {}

        estado = cleaned_data.get('estado')
        formato = cleaned_data.get('formato_partido')
        total_sets = 3 if formato == "3-2" else 5
        sets_necesarios_para_ganar = 2 if formato == "3-2" else 3
        ultimo_set = 3 if formato == "3-2" else 5

        sets_local = 0
        sets_externo = 0
        sets_jugados = 0

        for i in range(1, total_sets + 1):
            local = cleaned_data.get(f'set{i}_local')
            externo = cleaned_data.get(f'set{i}_externo')

            if local is None and externo is None:
                continue  # Set vacío, se ignora

            if local is None or externo is None:
                errores[f'set{i}_local'] = "Set incompleto"
                errores[f'set{i}_externo'] = "Set incompleto"
                continue

            diferencia = abs(local - externo)
            if diferencia < 2:
                errores[f'set{i}_local'] = "Diferencia mínima de 2 puntos"
                errores[f'set{i}_externo'] = "Diferencia mínima de 2 puntos"
                continue

            puntaje_minimo = 15 if i == ultimo_set else 25
            if max(local, externo) < puntaje_minimo:
                errores[f'set{i}_local'] = f"Uno de los equipos debe llegar al menos a {puntaje_minimo} puntos"
                errores[f'set{i}_externo'] = f"Uno de los equipos debe llegar al menos a {puntaje_minimo} puntos"
                continue

            sets_jugados += 1

            if local > externo:
                sets_local += 1
            elif externo > local:
                sets_externo += 1

            # Detener si ya ganó alguien (no hace falta seguir validando sets vacíos)
            if estado == "finalizado" and (sets_local == sets_necesarios_para_ganar or sets_externo == sets_necesarios_para_ganar):
                break

        if estado == "finalizado":
            if sets_local < sets_necesarios_para_ganar and sets_externo < sets_necesarios_para_ganar:
                self.add_error('estado', f"El partido no puede marcarse como finalizado si ningún equipo ha ganado los {sets_necesarios_para_ganar} sets requeridos.")
            elif sets_local == sets_externo:
                self.add_error('estado', "No puede haber empate en sets. Verifica los resultados.")
            else:
                cleaned_data['ganador'] = 'local' if sets_local > sets_externo else 'externo'
        else:
            cleaned_data['ganador'] = None

        for campo, mensaje in errores.items():
            self.add_error(campo, mensaje)

        return cleaned_data
    

class EstadisticaForm(forms.ModelForm):
    class Meta:
        model = Estadistica
        fields = ['partido', 'puntos', 'saques', 'remates', 'bloqueos', 'armadas', 'recepciones', 
        'errores']

        widgets = {
            'partido': forms.Select(attrs={'class': 'form-select'}),
            'puntos': forms.NumberInput(attrs={'class': 'form-control'}),
            'saques': forms.NumberInput(attrs={'class': 'form-control'}),
            'remates': forms.NumberInput(attrs={'class': 'form-control'}),
            'bloqueos': forms.NumberInput(attrs={'class': 'form-control'}),
            'armadas': forms.NumberInput(attrs={'class': 'form-control'}),
            'recepciones': forms.NumberInput(attrs={'class': 'form-control'}),
            'errores': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        atleta = kwargs.pop('atleta', None)
        super().__init__(*args, **kwargs)

        if atleta:
            equipos = atleta.equipo_set.all()
            self.fields['partido'].queryset = Partido.objects.filter(equipo_local__in=equipos).order_by('-fecha')
        else:
            self.fields['partido'].queryset = Partido.objects.none()

class AdministradorForm(forms.ModelForm):
    class Meta:
        model = Administrador
        fields = ["nombre", "apellido", "cedula", "fecha_nacimiento", "telefono"]