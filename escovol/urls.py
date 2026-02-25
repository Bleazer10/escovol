from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views

from .views import menu_principal, bienvenida, LoginPersonalizado

urlpatterns = [
    path('', bienvenida, name='bienvenida'),
    path('menu/', menu_principal, name='menu_principal'),

    path('admin/', admin.site.urls),
    path('atletas/', include('atletas.urls')),

    path('login/', LoginPersonalizado.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='bienvenida'), name='logout'),
]
