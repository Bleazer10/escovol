"""
URL configuration for escovol project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from escovol import views  # Vista del menú principal
from .views import menu_principal, bienvenida
from django.contrib.auth import views as auth_views
from escovol.views import LoginPersonalizado

urlpatterns = [
    path('', bienvenida, name='bienvenida'),
    path('menu', menu_principal, name='menu_principal'),
    path('admin/', admin.site.urls),
    path('atletas/', include('atletas.urls')),

    # Login personalizado
    path('login/', LoginPersonalizado.as_view(), name='login'),
    # Logout: redirige a 'bienvenida'
    path('logout/', auth_views.LogoutView.as_view(next_page='bienvenida'), name='logout'),

    # Opcional: rutas alternativas si las necesitas
    # path('accounts/login/', LoginPersonalizado.as_view(), name='login'),
    # path('accounts/logout/', auth_views.LogoutView.as_view(next_page='bienvenida'), name='logout'),
]


