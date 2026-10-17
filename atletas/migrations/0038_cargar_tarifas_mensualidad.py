from decimal import Decimal

from django.db import migrations
from django.utils import timezone


def cargar_tarifas_iniciales(apps, schema_editor):
    TarifaMensual = apps.get_model(
        "atletas",
        "TarifaMensual"
    )

    # Históricamente OLYMPO cobraba $5
    # hasta marzo de 2026.
    TarifaMensual.objects.update_or_create(
        vigente_desde=timezone.datetime(
            2026, 1, 1
        ).date(),
        defaults={
            "monto_usd": Decimal("5.00"),
            "tolerancia_usd": Decimal("0.10"),
        },
    )

    # Desde abril de 2026 la mensualidad
    # pasa oficialmente a $7.
    TarifaMensual.objects.update_or_create(
        vigente_desde=timezone.datetime(
            2026, 4, 1
        ).date(),
        defaults={
            "monto_usd": Decimal("7.00"),
            "tolerancia_usd": Decimal("0.10"),
        },
    )


def eliminar_tarifas_iniciales(apps, schema_editor):
    TarifaMensual = apps.get_model(
        "atletas",
        "TarifaMensual"
    )

    TarifaMensual.objects.filter(
        vigente_desde__in=[
            timezone.datetime(
                2026, 1, 1
            ).date(),
            timezone.datetime(
                2026, 4, 1
            ).date(),
        ]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        (
            "atletas",
            "0037_tarifamensual_tasacambio_pagomensualidad",
        ),
    ]

    operations = [
        migrations.RunPython(
            cargar_tarifas_iniciales,
            eliminar_tarifas_iniciales,
        ),
    ]