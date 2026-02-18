from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('atletas', '0003_fix_user_relations'),
    ]

    operations = [
        migrations.AlterField(
            model_name='atleta',
            name='user',
            field=models.CharField(max_length=255, null=True, blank=True, db_column='user_id', help_text='ID del usuario en Supabase (uuid)'),
        ),
        migrations.AlterField(
            model_name='entrenador',
            name='user',
            field=models.CharField(max_length=255, null=True, blank=True, db_column='user_id', help_text='ID del usuario en Supabase (uuid)'),
        ),
        migrations.AlterField(
            model_name='administrador',
            name='usuario',
            field=models.CharField(max_length=255, null=True, blank=True, db_column='user_id', help_text='ID del usuario en Supabase (uuid)'),
        ),
    ]
