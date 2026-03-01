from datetime import date, datetime
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import Sum
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages

from atletas.models import Atleta, Mensualidad, Equipo


# ✅ Si luego quieres hacerlo configurable, aquí lo conviertes en setting/constante global
CUOTA_MENSUAL = 8.0


@login_required
def menu_principal(request):
    hoy = date.today()
    mes_actual = hoy.month
    año_actual = hoy.year

    total_atletas = Atleta.objects.count()
    total_equipos = Equipo.objects.count()

    mensualidades_mes = Mensualidad.objects.filter(mes=mes_actual, año=año_actual)

    total_recaudado = float(mensualidades_mes.aggregate(total=Sum("monto_pagado"))["total"] or 0)

    exonerados = mensualidades_mes.filter(exonerado=True).count()
    al_dia = mensualidades_mes.filter(exonerado=False, monto_pagado__gte=CUOTA_MENSUAL).count()
    total_mensualidades = mensualidades_mes.count()
    deudores = max(total_mensualidades - al_dia - exonerados, 0)

    context = {
        "total_atletas": total_atletas,
        "total_equipos": total_equipos,
        "total_recaudado": total_recaudado,
        "al_dia": al_dia,
        "exonerados": exonerados,
        "deudores": deudores,
        "mes_actual": mes_actual,
        "año_actual": año_actual,
    }

    return render(request, "menu_principal.html", context)


def bienvenida(request):
    return render(request, "bienvenida.html")


class LoginPersonalizado(LoginView):
    template_name = "registration/login.html"

    def get_success_url(self):
        return reverse("menu_principal")

    def form_valid(self, form):
        user = form.get_user()

        if not user.is_active:
            messages.error(self.request, "Tu usuario está inactivo. Contacta al administrador.")
            return redirect("login")

        return super().form_valid(form)