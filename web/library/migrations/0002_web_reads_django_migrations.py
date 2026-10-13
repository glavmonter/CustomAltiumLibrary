from django.db import migrations

from library.schema_sql import run_sql_file


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0001_initial'),
    ]

    operations = [
        run_sql_file('0002_web_reads_django_migrations.sql',
                     reverse_sql='REVOKE SELECT ON public.django_migrations FROM library_web;'),
    ]
