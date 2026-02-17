from django.contrib import admin
from .models import Administrador
# Register your models here.

@admin.register(Administrador)
class AdministradorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "apellido", "cedula", "telefono")
    search_fields = ("nombre", "apellido", "cedula")
