# Начальная схема БД: SQL из sql/0001_initial.sql + описание неуправляемых моделей для Django.

import django.db.models.functions.comparison
import django.db.models.functions.datetime
import django.db.models.functions.text
from django.db import migrations, models

from library.schema_sql import run_sql_file


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    # Права по умолчанию на public (см. конец SQL) должны действовать до создания таблиц Django
    run_before = [
        ('contenttypes', '0001_initial'),
        ('auth', '0001_initial'),
        ('admin', '0001_initial'),
        ('sessions', '0001_initial'),
    ]

    operations = [
        run_sql_file('0001_initial.sql', reverse_sql='DROP SCHEMA altium CASCADE; DROP SCHEMA lib CASCADE;'),
        migrations.CreateModel(
            name='Component',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('design_item_id', models.GeneratedField(db_persist=True, expression=django.db.models.functions.text.Concat(models.Value('CMP-'), django.db.models.functions.text.LPad(django.db.models.functions.comparison.Cast('id', models.TextField()), 6, models.Value('0'))), output_field=models.TextField(), verbose_name='Design Item ID')),
                ('manufacturer_pn', models.CharField(max_length=255, verbose_name='номер у производителя (MPN)')),
                ('comment', models.CharField(blank=True, help_text='Пусто — в Altium подставится Value, а если нет и его — MPN', max_length=255, null=True, verbose_name='Comment')),
                ('description', models.TextField(blank=True, null=True, verbose_name='описание')),
                ('value', models.CharField(blank=True, max_length=255, null=True, verbose_name='Value')),
                ('voltage', models.CharField(blank=True, max_length=255, null=True, verbose_name='Voltage')),
                ('tolerance', models.CharField(blank=True, max_length=255, null=True, verbose_name='Tolerance')),
                ('value_si', models.FloatField(blank=True, help_text='для фильтров: 10k → 10000, 100nF → 1e-7', null=True, verbose_name='значение в СИ')),
                ('voltage_v', models.FloatField(blank=True, null=True, verbose_name='напряжение, В')),
                ('tolerance_pct', models.FloatField(blank=True, null=True, verbose_name='допуск, %')),
                ('datasheet_url', models.URLField(blank=True, max_length=2000, null=True, verbose_name='даташит (HelpURL)')),
                ('status', models.CharField(choices=[('active', 'активный'), ('nrnd', 'не для новых разработок'), ('obsolete', 'снят с производства'), ('draft', 'черновик (не виден в Altium)')], default='active', max_length=16, verbose_name='статус')),
                ('created_at', models.DateTimeField(db_default=django.db.models.functions.datetime.Now(), editable=False, verbose_name='создан')),
                ('updated_at', models.DateTimeField(db_default=django.db.models.functions.datetime.Now(), editable=False, verbose_name='изменён')),
            ],
            options={
                'verbose_name': 'компонент',
                'verbose_name_plural': 'компоненты',
                'db_table': 'components',
                'ordering': ['id'],
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='ComponentClass',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('name', models.CharField(help_text='Значение параметра Class в Altium', max_length=255, verbose_name='название')),
                ('view_name', models.CharField(blank=True, help_text='Имя представления altium.<имя>: латиница в нижнем регистре, цифры, _. Пусто — класс не выводится отдельной вкладкой. Включает дочерние классы.', max_length=51, null=True, unique=True, verbose_name='вкладка в Altium')),
                ('designator_prefix', models.CharField(blank=True, max_length=10, null=True, verbose_name='префикс позиционного обозначения')),
                ('sort_order', models.IntegerField(default=0, verbose_name='порядок')),
            ],
            options={
                'verbose_name': 'класс компонентов',
                'verbose_name_plural': 'классы компонентов',
                'db_table': 'component_classes',
                'ordering': ['sort_order', 'name'],
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='ComponentFootprint',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('slot', models.PositiveSmallIntegerField(choices=[(1, '1 — основное'), (2, '2 — альтернативное'), (3, '3 — альтернативное'), (4, '4 — альтернативное')], verbose_name='позиция')),
            ],
            options={
                'verbose_name': 'посадочное место компонента',
                'verbose_name_plural': 'посадочные места (1 — основное, 2..4 — альтернативные)',
                'db_table': 'component_footprints',
                'ordering': ['slot'],
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='ComponentSupplier',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('slot', models.PositiveSmallIntegerField(choices=[(1, '1'), (2, '2'), (3, '3')], verbose_name='позиция')),
                ('supplier_pn', models.CharField(max_length=255, verbose_name='артикул в магазине')),
                ('product_url', models.URLField(blank=True, help_text='Пусто — строится по шаблону магазина', max_length=2000, null=True, verbose_name='ссылка на товар')),
            ],
            options={
                'verbose_name': 'магазин компонента',
                'verbose_name_plural': 'магазины (не более трёх)',
                'db_table': 'component_suppliers',
                'ordering': ['slot'],
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='Footprint',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('footprint_ref', models.CharField(help_text='имя посадочного места в PcbLib', max_length=255, verbose_name='Footprint Ref')),
                ('footprint_path', models.CharField(help_text='путь к .PcbLib относительно .DbLib', max_length=1000, verbose_name='Footprint Path')),
                ('description', models.TextField(blank=True, null=True, verbose_name='описание')),
                ('created_at', models.DateTimeField(db_default=django.db.models.functions.datetime.Now(), editable=False)),
                ('updated_at', models.DateTimeField(db_default=django.db.models.functions.datetime.Now(), editable=False)),
            ],
            options={
                'verbose_name': 'посадочное место',
                'verbose_name_plural': 'посадочные места',
                'db_table': 'footprints',
                'ordering': ['footprint_ref'],
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='Manufacturer',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255, unique=True, verbose_name='название')),
                ('website', models.URLField(blank=True, max_length=2000, null=True, verbose_name='сайт')),
                ('created_at', models.DateTimeField(db_default=django.db.models.functions.datetime.Now(), editable=False)),
            ],
            options={
                'verbose_name': 'производитель',
                'verbose_name_plural': 'производители',
                'db_table': 'manufacturers',
                'ordering': ['name'],
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='Media',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('sha256', models.BinaryField(unique=True)),
                ('mime_type', models.TextField()),
                ('data', models.BinaryField()),
                ('width_px', models.IntegerField(blank=True, null=True)),
                ('height_px', models.IntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(db_default=django.db.models.functions.datetime.Now(), editable=False)),
            ],
            options={
                'verbose_name': 'картинка',
                'verbose_name_plural': 'картинки',
                'db_table': 'media',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='Supplier',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255, unique=True, verbose_name='название')),
                ('website', models.URLField(blank=True, max_length=2000, null=True, verbose_name='сайт')),
                ('product_url_template', models.CharField(blank=True, help_text='{pn} заменяется на артикул, напр. https://www.lcsc.com/product-detail/{pn}.html', max_length=2000, null=True, verbose_name='шаблон ссылки на товар')),
            ],
            options={
                'verbose_name': 'магазин',
                'verbose_name_plural': 'магазины',
                'db_table': 'suppliers',
                'ordering': ['name'],
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='Symbol',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('library_ref', models.CharField(help_text='имя символа в SchLib', max_length=255, verbose_name='Library Ref')),
                ('library_path', models.CharField(help_text='путь к .SchLib относительно .DbLib', max_length=1000, verbose_name='Library Path')),
                ('created_at', models.DateTimeField(db_default=django.db.models.functions.datetime.Now(), editable=False)),
                ('updated_at', models.DateTimeField(db_default=django.db.models.functions.datetime.Now(), editable=False)),
            ],
            options={
                'verbose_name': 'символ (УГО)',
                'verbose_name_plural': 'символы (УГО)',
                'db_table': 'symbols',
                'ordering': ['library_ref'],
                'managed': False,
            },
        ),
    ]
