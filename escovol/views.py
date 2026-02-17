from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import datetime
from atletas.models import Atleta, Mensualidad, Equipo, Partido, Estadistica
from datetime import datetime, timedelta
from django.db.models import Sum, Max
from collections import defaultdict
from django.template.loader import render_to_string
from django.http import JsonResponse, HttpResponse
from collections import Counter
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages

@login_required
def menu_principal(request):
    hoy = datetime.now()
    semana_offset = int(request.GET.get('semana', 0))  # Desplazamiento de semanas
    inicio_semana = hoy - timedelta(days=hoy.weekday()) + timedelta(weeks=semana_offset)
    fin_semana = inicio_semana + timedelta(days=6)

    # Totales generales
    mes_actual = hoy.month
    año_actual = hoy.year
    mes_anterior = mes_actual - 1 if mes_actual > 1 else 12
    año_mes_anterior = año_actual if mes_actual > 1 else año_actual - 1

    total_atletas = Atleta.objects.count()
    total_recaudado = Mensualidad.objects.filter(
        mes=mes_actual, año=año_actual
    ).aggregate(total=Sum('monto_pagado'))['total'] or 0

    # Establecer fechas
    hoy = datetime.now()
    mes_actual = hoy.month
    año_actual = hoy.year
    mes_anterior = mes_actual - 1 if mes_actual > 1 else 12
    año_mes_anterior = año_actual if mes_actual > 1 else año_actual - 1

    # Estadísticas del mes actual para roles
    estadisticas_mes_actual = Estadistica.objects.select_related('atleta').filter(
        partido__fecha__month=mes_actual,
        partido__fecha__year=año_actual
    )

    # Estadísticas del mes anterior para jugador más destacado
    estadisticas_mes_anterior = Estadistica.objects.select_related('atleta').filter(
        partido__fecha__month=mes_anterior,
        partido__fecha__year=año_mes_anterior
    )

    # =======================
    # Jugador más destacado (MES ANTERIOR)
    # =======================
    jugador_puntos_netos = defaultdict(int)
    for estad in estadisticas_mes_anterior:
        jugador_puntos_netos[estad.atleta.id] += estad.puntos - estad.errores

    jugador_destacado = None
    if jugador_puntos_netos:
        max_puntos = max(jugador_puntos_netos.values())
        ids_empate = [aid for aid, puntos in jugador_puntos_netos.items() if puntos == max_puntos]
        atletas_empate = Atleta.objects.filter(id__in=ids_empate)[:3]
        jugador_destacado = [{
            'nombre': atleta.nombre,
            'apellido': atleta.apellido,
            'categoria': atleta.categoria,
            'total_puntos': max_puntos
        } for atleta in atletas_empate]

    # =======================
    # Mejores por rol (MES ACTUAL)
    # =======================
    rol_colors = {
        'saques': 'success',
        'remates': 'danger',
        'armadas': 'info',
        'bloqueos': 'warning',
        'recepciones': 'dark',
    }

    mejores_por_rol_list = [
        {'rol': 'saques', 'titulo': 'Mejor Sacador', 'icono': 'fa-bullseye'},
        {'rol': 'remates', 'titulo': 'Mejor Rematador', 'icono': 'fa-hand-rock'},
        {'rol': 'armadas', 'titulo': 'Mejor Armador', 'icono': 'fa-hands'},
        {'rol': 'bloqueos', 'titulo': 'Mejor Bloqueador', 'icono': 'fa-shield-alt'},
        {'rol': 'recepciones', 'titulo': 'Mejor Recepción', 'icono': 'fa-handshake'},
    ]

    for item in mejores_por_rol_list:
        rol = item['rol']
        valores = estadisticas_mes_actual.values('atleta').annotate(total=Sum(rol)).order_by('-total')

        if valores:
            max_valor = valores[0]['total']

            # 👉 condición para evitar mostrar jugadores con 0
            if max_valor and max_valor > 0:
                ids_empate = [v['atleta'] for v in valores if v['total'] == max_valor]
                estadisticas_filtradas = estadisticas_mes_actual.filter(atleta__id__in=ids_empate)

                errores_por_atleta = defaultdict(int)
                for est in estadisticas_filtradas:
                    errores_por_atleta[est.atleta.id] += est.errores

                atletas_con_errores = [{'id': aid, 'errores': errores_por_atleta[aid]} for aid in ids_empate]
                atletas_con_errores.sort(key=lambda x: x['errores'])

                mejores_ids = [a['id'] for a in atletas_con_errores[:3]]
                atletas = Atleta.objects.filter(id__in=mejores_ids)

                atletas_finales = sorted(atletas, key=lambda a: errores_por_atleta[a.id])

                item['jugadores'] = [{
                    'nombre': a.nombre,
                    'apellido': a.apellido,
                    'categoria': a.categoria,
                    'total': max_valor,
                    'errores': errores_por_atleta[a.id]
                } for a in atletas_finales]

                item['valor'] = max_valor
            else:
                item['jugadores'] = []
                item['valor'] = 0
        else:
            item['jugadores'] = []
            item['valor'] = 0

        item['color'] = rol_colors.get(rol, 'secondary')


    # Partidos jugados en el mes actual
    partidos_mes_actual = Partido.objects.filter(
        fecha__month=mes_actual,
        fecha__year=año_actual,
        estado='finalizado'
    )

    # Total jugados
    total_partidos_mes = partidos_mes_actual.count()

    # Total ganados por Local
    partidos_ganados_mes = partidos_mes_actual.filter(ganador='local').count()

    # Contar victorias por equipo de Local
    victorias_por_equipo = Counter()

    def contar_sets_ganados(partido):
        sets_local = 0
        sets_externo = 0
        for i in range(1, 6):
            local = getattr(partido, f"set{i}_local")
            externo = getattr(partido, f"set{i}_externo")
            if local is not None and externo is not None:
                if local > externo:
                    sets_local += 1
                elif externo > local:
                    sets_externo += 1
        return sets_local, sets_externo

    for partido in partidos_mes_actual:
        sets_local, sets_externo = contar_sets_ganados(partido)
        if sets_local > sets_externo and partido.equipo_local:
            victorias_por_equipo[partido.equipo_local.id] += 1

    # Determinar equipos más ganadores (puede haber empate)
    equipos_mas_ganadores = []
    equipo_destacado = []

    if victorias_por_equipo:
        max_victorias = max(victorias_por_equipo.values())
        ids_empate = [eid for eid, v in victorias_por_equipo.items() if v == max_victorias]
        equipos_mas_ganadores = Equipo.objects.filter(id__in=ids_empate)

        for eq in equipos_mas_ganadores:
            equipo_destacado.append({
                'nombre': eq.nombre,
                'total_victorias': max_victorias
            })

    # Partidos de la semana actual según offset
    partidos_semana = Partido.objects.filter(
        fecha__range=(inicio_semana.date(), fin_semana.date())
    ).order_by('fecha', 'hora')

    partidos_semana = [
        p for p in partidos_semana
        if p.fecha > hoy.date() or (p.fecha == hoy.date() and p.hora > hoy.time())
    ]

    # Mapeo manual sin acentos
    dias_orden = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado', 'Domingo']
    calendario = {dia: [] for dia in dias_orden}

    for partido in partidos_semana:
        dia_index = (partido.fecha.weekday())  # 0 = lunes
        dia_nombre = dias_orden[dia_index]
        calendario[dia_nombre].append(partido)

    context = {
        'total_atletas': total_atletas,
        'partidos_ganados_mes': partidos_ganados_mes,
        'total_partidos_mes': total_partidos_mes,
        'total_recaudado': total_recaudado,
        'jugador_destacado': jugador_destacado,
        'mejores_por_rol': mejores_por_rol_list,
        'equipo_destacado': equipo_destacado,
        'calendario': calendario,
        'inicio_semana': inicio_semana.date(),
        'fin_semana': fin_semana.date(),
        'semana_offset': semana_offset,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('fragmentos/calendario_semanal.html', context, request=request)
        return HttpResponse(html)

    
    return render(request, 'menu_principal.html', context)

def bienvenida(request):
    return render(request, 'bienvenida.html')

# escovol/views.py

from django.contrib.auth.views import LoginView
from django.shortcuts import redirect

class LoginPersonalizado(LoginView):
    template_name = 'registration/login.html'

    def get_success_url(self):
        # Todos los usuarios, sin importar el rol, van al menú principal
        return reverse('menu_principal')

    def form_valid(self, form):
        user = form.get_user()
        # Verificamos si el usuario está inactivo
        if not user.is_active:
            return redirect('login')  # lo devuelve al login
        return super().form_valid(form)