from django import forms
from .models import Atleta, Equipo, Administrador
from django.contrib.auth.models import User
from django.db import transaction

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


# forms.py
class EquipoForm(forms.ModelForm):
    class Meta:
        model = Equipo
        fields = ['nombre', 'categoria', 'sexo_equipo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'categoria': forms.TextInput(attrs={'class': 'form-control'}),
            'sexo_equipo': forms.Select(attrs={'class': 'form-select'}),
        }

class AdministradorForm(forms.ModelForm):
    # Campos del User (extra)
    username = forms.CharField(label="Usuario", max_length=150)
    email = forms.EmailField(label="Email", required=False)
    password = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput,
        required=False,
        help_text="Déjalo vacío si no quieres cambiarla."
    )
    is_active = forms.BooleanField(label="Activo", required=False, initial=True)

    class Meta:
        model = Administrador
        fields = ["nombre", "apellido", "cedula", "fecha_nacimiento", "telefono"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "apellido": forms.TextInput(attrs={"class": "form-control"}),
            "cedula": forms.TextInput(attrs={"class": "form-control"}),
            "fecha_nacimiento": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "telefono": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Si estamos editando, precargar datos del User
        if self.instance and self.instance.pk and self.instance.usuario_id:
            user = self.instance.usuario
            self.fields["username"].initial = user.username
            self.fields["email"].initial = user.email
            self.fields["is_active"].initial = user.is_active

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            raise forms.ValidationError("El usuario es obligatorio.")

        qs = User.objects.filter(username=username)

        # Si editamos, permitir el mismo username del mismo user
        if self.instance and self.instance.pk and self.instance.usuario_id:
            qs = qs.exclude(pk=self.instance.usuario_id)

        if qs.exists():
            raise forms.ValidationError("Ese usuario ya existe.")
        return username

    def clean_password(self):
        pwd = (self.cleaned_data.get("password") or "").strip()

        # Si estamos creando (no existe Administrador aún), la contraseña es obligatoria
        if not self.instance.pk and not pwd:
            raise forms.ValidationError("La contraseña es obligatoria al crear el usuario.")

        return pwd

    @transaction.atomic
    def save(self, commit=True):
        admin_obj = super().save(commit=False)

        username = self.cleaned_data["username"]
        email = self.cleaned_data.get("email", "") or ""
        password = self.cleaned_data.get("password", "") or ""
        is_active = bool(self.cleaned_data.get("is_active", True))

        # Crear o actualizar el User
        if admin_obj.pk and admin_obj.usuario_id:
            user = admin_obj.usuario
            user.username = username
            user.email = email
            user.is_active = is_active
            if password:
                user.set_password(password)
            if commit:
                user.save()
        else:
            user = User(username=username, email=email, is_active=is_active)
            user.set_password(password)
            if commit:
                user.save()
            admin_obj.usuario = user

        if commit:
            admin_obj.save()

        return admin_obj