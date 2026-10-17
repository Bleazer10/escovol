from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            'atletas',
            '0042_mensualidad_exonerado_en_mensualidad_exonerado_por_and_more',
        ),
    ]

    operations = [
        migrations.AddField(
            model_name='mensualidad',
            name='en_control',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'Indica si este período forma parte '
                    'del control real de mensualidades.'
                ),
            ),
        ),
    ]