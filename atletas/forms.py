# atletas/forms.py
from django import forms
from .models import Estadistica, Entrenador, Atleta, Campeonato, Partido, Equipo, Administrador
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class AtletaForm(forms.ModelForm):
    class Meta:
        model = Atleta
        fields = [
            'nombre', 'apellido', 'fecha_nacimiento', 'sexo', 'cedula', 'telefono',
            'direccion', 'numero_camisa', 'posicion', 'turno',
            'salto', 'alcance', 'peso', 'estatura',
            'representante_nombre', 'representante_apellido',
            'representante_cedula', 'representante_telefono',
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'apellido': forms.TextInput(attrs={'class': 'form-control'}),
            'fecha_nacimiento': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'sexo': forms.Select(choices=Atleta._meta.get_field('sexo').choices, attrs={'class': 'form-select'}),
            'cedula': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2,
                'placeholder': 'Ej: Av. Principal, Casa 45, Maracay'
            }),
            'numero_camisa': forms.NumberInput(attrs={'class': 'form-control'}),
            'posicion': forms.Select(choices=Atleta._meta.get_field('posicion').choices, attrs={'class': 'form-select'}),
            'turno': forms.Select(choices=Atleta._meta.get_field('turno').choices, attrs={'class': 'form-select'}),
            'salto': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Ej: 2.85'}),
            'alcance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Ej: 2.45'}),
            'peso': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'placeholder': 'Ej: 65.5'}),
            'estatura': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Ej: 1.75'}),
            'representante_nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'representante_apellido': forms.TextInput(attrs={'class': 'form-control'}),
            'representante_cedula': forms.TextInput(attrs={'class': 'form-control'}),
            'representante_telefono': forms.TextInput(attrs={'class': 'form-control'}),
        }


class UsuarioForm(forms.Form):
    """
    Formulario para crear o editar las credenciales de un usuario.

    Ya NO hereda de ModelForm(User) porque las contraseñas se gestionan
    en Supabase Auth. Django solo almacena el UUID y el email.

    - Al CREAR: username, email y password son obligatorios.
    - Al EDITAR: password es opcional (vacío = no cambiar).
    """
    username = forms.CharField(
        max_length=150,
        label="Nombre de usuario",
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    email = forms.EmailField(
        required=False,
        label="Email",
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False, attrs={'class': 'form-control'}),
        required=False,
        label="Contraseña",
        help_text="Mínimo 6 caracteres. Dejar vacío para no cambiar (solo en edición).",
    )
    is_active = forms.ChoiceField(
        choices=[("True", "Activo"), ("False", "Inactivo")],
        label="Estado",
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, instance: User = None, **kwargs):
        """
        Acepta instance=<User> para pre-rellenar al editar.
        En modo edición el username se muestra pero no se edita
        (Supabase no permite cambiar el UUID).
        """
        initial = kwargs.get('initial', {})
        if instance is not None:
            # En edición mostramos el username guardado (puede ser el UUID o el username real)
            # Para la UI mostramos el email como referencia más amigable
            initial.setdefault('username', instance.username)
            initial.setdefault('email', instance.email)
            initial.setdefault('is_active', str(instance.is_active))
        kwargs['initial'] = initial
        super().__init__(*args, **kwargs)
        self._instance = instance

        # En edición el username solo es informativo; el UUID no cambia
        if instance is not None:
            self.fields['username'].disabled = True
            self.fields['username'].help_text = "El nombre de usuario no se puede cambiar."

    def clean_is_active(self):
        return self.cleaned_data['is_active'] == "True"

    def clean_password(self):
        pwd = self.cleaned_data.get('password', '')
        if pwd and len(pwd) < 6:
            raise forms.ValidationError("La contraseña debe tener al menos 6 caracteres.")
        return pwd

    def get_password(self) -> str | None:
        """Devuelve la nueva contraseña si el usuario la escribió, o None."""
        return self.cleaned_data.get('password') or None

    def apply_to_user(self, user: User) -> User:
        """
        Aplica los cambios de email/estado al User de Django.
        La contraseña se actualiza por separado en Supabase (ver views).
        """
        user.email = self.cleaned_data.get('email') or user.email
        user.is_active = self.cleaned_data['is_active']
        user.save()
        return user


class EntrenadorForm(forms.ModelForm):
    class Meta:
        model = Entrenador
        fields = ['nombre', 'apellido', 'cedula', 'fecha_nacimiento', 'telefono']
        widgets = {
            'fecha_nacimiento': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.get('instance')
        super().__init__(*args, **kwargs)

    def clean_cedula(self):
        cedula = self.cleaned_data.get('cedula')
        qs = Entrenador.objects.filter(cedula=cedula)
        if self.instance and self.instance.pk:
            qs = qs.exclude(id=self.instance.pk)
        if qs.exists():
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
            'equipo_local', 'equipo_externo', 'fecha', 'hora', 'lugar',
            'campeonato', 'estado', 'formato_partido', 'observaciones',
            'set1_local', 'set1_externo', 'set2_local', 'set2_externo',
            'set3_local', 'set3_externo', 'set4_local', 'set4_externo',
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
        sets_necesarios = 2 if formato == "3-2" else 3
        ultimo_set = 3 if formato == "3-2" else 5
        sets_local = sets_externo = 0

        for i in range(1, total_sets + 1):
            local = cleaned_data.get(f'set{i}_local')
            externo = cleaned_data.get(f'set{i}_externo')
            if local is None and externo is None:
                continue
            if local is None or externo is None:
                errores[f'set{i}_local'] = "Set incompleto"
                errores[f'set{i}_externo'] = "Set incompleto"
                continue
            if abs(local - externo) < 2:
                errores[f'set{i}_local'] = "Diferencia mínima de 2 puntos"
                errores[f'set{i}_externo'] = "Diferencia mínima de 2 puntos"
                continue
            puntaje_minimo = 15 if i == ultimo_set else 25
            if max(local, externo) < puntaje_minimo:
                errores[f'set{i}_local'] = f"Mínimo {puntaje_minimo} puntos requeridos"
                errores[f'set{i}_externo'] = f"Mínimo {puntaje_minimo} puntos requeridos"
                continue
            if local > externo:
                sets_local += 1
            else:
                sets_externo += 1
            if estado == "finalizado" and (sets_local == sets_necesarios or sets_externo == sets_necesarios):
                break

        if estado == "finalizado":
            if sets_local < sets_necesarios and sets_externo < sets_necesarios:
                self.add_error('estado', f"Ningún equipo ha ganado los {sets_necesarios} sets requeridos.")
            elif sets_local == sets_externo:
                self.add_error('estado', "No puede haber empate en sets.")
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
        fields = ['partido', 'puntos', 'saques', 'remates', 'bloqueos', 'armadas', 'recepciones', 'errores']
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
