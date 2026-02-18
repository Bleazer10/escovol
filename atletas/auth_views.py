# atletas/auth_views.py

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .utils.roles import es_admin, es_entrenador, es_atleta
from .models import Atleta


def login_view(request):
    """Vista de inicio de sesión. Redirige según el rol del usuario."""
    if request.user.is_authenticated:
        return _redirigir_por_rol(request.user)

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if not user.is_active:
                messages.error(request, 'Tu cuenta está desactivada. Contacta al administrador.')
                return render(request, 'registration/login.html', {'error': True})

            login(request, user)
            return _redirigir_por_rol(user)
        else:
            messages.error(request, 'Credenciales incorrectas. Inténtalo de nuevo.')
            return render(request, 'registration/login.html', {'error': True})

    return render(request, 'registration/login.html')


def _redirigir_por_rol(user):
    """Devuelve un redirect según el grupo del usuario."""
    if es_admin(user):
        return redirect('menu_principal')
    elif es_entrenador(user):
        return redirect('menu_principal')
    elif es_atleta(user):
        # Buscar el ID del atleta vinculado
        atleta = Atleta.objects.filter(user=user.username).first()
        if atleta:
            return redirect('detalle_atleta', atleta_id=atleta.id)
        return redirect('bienvenida')
    # Fallback: superuser u otros
    return redirect('menu_principal')


def logout_view(request):
    """Cierra la sesión y redirige a la página de bienvenida."""
    logout(request)
    messages.success(request, 'Sesión cerrada correctamente.')
    return redirect('bienvenida')


@login_required
def profile_view(request):
    """Perfil del usuario autenticado."""
    return render(request, 'atletas/profile.html', {'user': request.user})


def bienvenida_view(request):
    """Página pública de bienvenida."""
    if request.user.is_authenticated:
        return _redirigir_por_rol(request.user)
    return render(request, 'bienvenida.html')


def register_view(request):
    """Registro de nuevos usuarios (vía Supabase)."""
    if request.user.is_authenticated:
        return _redirigir_por_rol(request.user)

    if request.method == 'POST':
        email    = request.POST.get('email', '').strip()
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        password2 = request.POST.get('password2', '').strip()
        nombre   = request.POST.get('nombre', '').strip()
        rol      = request.POST.get('rol', 'Atleta')

        if password != password2:
            return render(request, 'atletas/register.html',
                          {'error': 'Las contraseñas no coinciden.'})

        try:
            from supabase import create_client
            from django.conf import settings

            supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
            response = supabase.auth.sign_up({
                "email": email,
                "password": password,
                "options": {
                    "data": {"username": username, "nombre": nombre, "rol": rol}
                }
            })

            if response.user:
                messages.success(request,
                    '¡Registro exitoso! Revisa tu correo para confirmar la cuenta.')
                return redirect('login')

            return render(request, 'atletas/register.html',
                          {'error': 'Error en el registro. Inténtalo de nuevo.'})

        except Exception as e:
            return render(request, 'atletas/register.html',
                          {'error': f'Error: {str(e)}'})

    return render(request, 'atletas/register.html')