# atletas/auth_views.py
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required

def login_view(request):
    """Vista de inicio de sesión que usa tu template existente"""
    if request.user.is_authenticated:
        return redirect('lista_atletas')
    
    if request.method == 'POST':
        # Tu template usa 'username' pero puede ser email o nombre de usuario
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        # Authenticate usará tu SupabaseAuthBackend
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            messages.success(request, f"¡Bienvenido {user.email}!")
            
            # Redirigir según el grupo
            if user.groups.filter(name='Administrador').exists():
                return redirect('administracion')
            elif user.groups.filter(name='Entrenador').exists():
                return redirect('lista_entrenadores')
            else:
                return redirect('lista_atletas')
        else:
            # Para que tu template muestre el error con form.errors
            # Creamos un error en el formulario
            return render(request, 'atletas/login.html', {'form': type('obj', (object,), {'errors': True})})
    
    # GET request - mostrar formulario vacío
    return render(request, 'atletas/login.html', {'form': type('obj', (object,), {'errors': False})})

def logout_view(request):
    """Cerrar sesión"""
    logout(request)
    messages.success(request, "Sesión cerrada correctamente")
    return redirect('bienvenida')

@login_required
def profile_view(request):
    """Ver perfil del usuario"""
    return render(request, 'atletas/profile.html', {
        'user': request.user
    })

def bienvenida_view(request):
    """Página de bienvenida (pública)"""
    if request.user.is_authenticated:
        return redirect('lista_atletas')
    return render(request, 'atletas/bienvenida.html')

# atletas/auth_views.py - Añade esta función

def register_view(request):
    """Vista de registro de nuevos usuarios"""
    if request.user.is_authenticated:
        return redirect('lista_atletas')
    
    if request.method == 'POST':
        email = request.POST.get('email')
        username = request.POST.get('username')
        password = request.POST.get('password')
        password2 = request.POST.get('password2')
        nombre = request.POST.get('nombre')
        rol = request.POST.get('rol', 'Atleta')  # Por defecto 'Atleta'
        
        # Validaciones básicas
        if password != password2:
            return render(request, 'atletas/register.html', {
                'error': 'Las contraseñas no coinciden'
            })
        
        try:
            from supabase import create_client
            import os
            
            supabase = create_client(
                os.getenv('SUPABASE_URL'),
                os.getenv('SUPABASE_ANON_KEY')
            )
            
            # Registrar en Supabase
            response = supabase.auth.sign_up({
                "email": email,
                "password": password,
                "options": {
                    "data": {
                        "username": username,
                        "nombre": nombre,
                        "rol": rol
                    }
                }
            })
            
            if response.user:
                messages.success(request, 
                    "¡Registro exitoso! Por favor revisa tu email para confirmar la cuenta.")
                return redirect('login')
            else:
                return render(request, 'atletas/register.html', {
                    'error': 'Error en el registro'
                })
                
        except Exception as e:
            return render(request, 'atletas/register.html', {
                'error': f'Error: {str(e)}'
            })
    
    # GET request
    return render(request, 'atletas/register.html')