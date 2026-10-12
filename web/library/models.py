"""Модели поверх схемы lib.

Все модели managed=False: структуру таблиц создают SQL-операции миграций (migrations/sql/),
Django только читает и пишет данные. Таблицы находятся по search_path (public,lib).
"""

from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Value
from django.db.models.functions import Cast, Concat, LPad, Now
from django.urls import reverse

FOOTPRINT_SLOTS = [(1, "1 — основное"), (2, "2 — альтернативное"), (3, "3 — альтернативное"),
                   (4, "4 — альтернативное")]
SUPPLIER_SLOTS = [(1, "1"), (2, "2"), (3, "3")]


class Media(models.Model):
    """Картинка УГО / посадочного места, хранится в БД (bytea), дедупликация по sha256."""

    id = models.BigAutoField(primary_key=True)
    sha256 = models.BinaryField(unique=True)
    mime_type = models.TextField()
    data = models.BinaryField()
    width_px = models.IntegerField(null=True, blank=True)
    height_px = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        managed = False
        db_table = "media"
        verbose_name = "картинка"
        verbose_name_plural = "картинки"

    def __str__(self):
        return f"#{self.pk} {self.mime_type}"

    def get_absolute_url(self):
        return reverse("library:media", args=[self.pk])


class Manufacturer(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField("название", max_length=255, unique=True)
    website = models.URLField("сайт", max_length=2000, null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        managed = False
        db_table = "manufacturers"
        ordering = ["name"]
        verbose_name = "производитель"
        verbose_name_plural = "производители"

    def __str__(self):
        return self.name


class Supplier(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField("название", max_length=255, unique=True)
    website = models.URLField("сайт", max_length=2000, null=True, blank=True)
    product_url_template = models.CharField(
        "шаблон ссылки на товар", max_length=2000, null=True, blank=True,
        help_text="{pn} заменяется на артикул, напр. https://www.lcsc.com/product-detail/{pn}.html")

    class Meta:
        managed = False
        db_table = "suppliers"
        ordering = ["name"]
        verbose_name = "магазин"
        verbose_name_plural = "магазины"

    def __str__(self):
        return self.name


class ComponentClass(models.Model):
    id = models.AutoField(primary_key=True)
    parent = models.ForeignKey("self", models.PROTECT, null=True, blank=True,
                               related_name="children", verbose_name="родительский класс")
    name = models.CharField("название", max_length=255, help_text="Значение параметра Class в Altium")
    view_name = models.CharField(
        "вкладка в Altium", max_length=51, null=True, blank=True, unique=True,
        validators=[RegexValidator(r"^[a-z][a-z0-9_]{0,50}$", "Латиница в нижнем регистре, цифры и _, "
                                                              "начинается с буквы.")],
        help_text="Имя представления altium.<имя>: латиница в нижнем регистре, цифры, _. "
                  "Пусто — класс не выводится отдельной вкладкой. Включает дочерние классы.")
    designator_prefix = models.CharField("префикс позиционного обозначения", max_length=10,
                                         null=True, blank=True)
    sort_order = models.IntegerField("порядок", default=0)

    class Meta:
        managed = False
        db_table = "component_classes"
        ordering = ["sort_order", "name"]
        verbose_name = "класс компонентов"
        verbose_name_plural = "классы компонентов"

    def __str__(self):
        return self.name


class Symbol(models.Model):
    """УГО: ссылка на символ в SchLib + картинка для сайта."""

    id = models.AutoField(primary_key=True)
    library_ref = models.CharField("Library Ref", max_length=255, help_text="имя символа в SchLib")
    library_path = models.CharField("Library Path", max_length=1000,
                                    help_text="путь к .SchLib относительно .DbLib")
    preview_media = models.ForeignKey(Media, models.SET_NULL, null=True, blank=True,
                                      related_name="+", verbose_name="картинка")
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    updated_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        managed = False
        db_table = "symbols"
        constraints = [models.UniqueConstraint(fields=["library_path", "library_ref"], name="symbols_uq")]
        ordering = ["library_ref"]
        verbose_name = "символ (УГО)"
        verbose_name_plural = "символы (УГО)"

    def __str__(self):
        return self.library_ref


class Footprint(models.Model):
    id = models.AutoField(primary_key=True)
    footprint_ref = models.CharField("Footprint Ref", max_length=255,
                                     help_text="имя посадочного места в PcbLib")
    footprint_path = models.CharField("Footprint Path", max_length=1000,
                                      help_text="путь к .PcbLib относительно .DbLib")
    description = models.TextField("описание", blank=True, null=True)
    preview_media = models.ForeignKey(Media, models.SET_NULL, null=True, blank=True,
                                      related_name="+", verbose_name="2D-вид")
    preview3d_media = models.ForeignKey(Media, models.SET_NULL, null=True, blank=True,
                                        related_name="+", verbose_name="3D-вид")
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    updated_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        managed = False
        db_table = "footprints"
        constraints = [models.UniqueConstraint(fields=["footprint_path", "footprint_ref"], name="footprints_uq")]
        ordering = ["footprint_ref"]
        verbose_name = "посадочное место"
        verbose_name_plural = "посадочные места"

    def __str__(self):
        return self.footprint_ref


class Component(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "активный"
        NRND = "nrnd", "не для новых разработок"
        OBSOLETE = "obsolete", "снят с производства"
        DRAFT = "draft", "черновик (не виден в Altium)"

    id = models.BigAutoField(primary_key=True)
    # Вычисляет БД (см. схему); выражение здесь только для полноты описания поля.
    design_item_id = models.GeneratedField(
        expression=Concat(Value("CMP-"), LPad(Cast("id", models.TextField()), 6, Value("0"))),
        output_field=models.TextField(), db_persist=True, verbose_name="Design Item ID")

    component_class = models.ForeignKey(ComponentClass, models.PROTECT, db_column="class_id",
                                        related_name="components", verbose_name="класс")
    manufacturer = models.ForeignKey(Manufacturer, models.PROTECT, related_name="components",
                                     verbose_name="производитель")
    manufacturer_pn = models.CharField("номер у производителя (MPN)", max_length=255)
    symbol = models.ForeignKey(Symbol, models.PROTECT, related_name="components",
                               verbose_name="символ (УГО)")

    comment = models.CharField("Comment", max_length=255, null=True, blank=True,
                               help_text="Пусто — в Altium подставится Value, а если нет и его — MPN")
    description = models.TextField("описание", blank=True, null=True)

    value = models.CharField("Value", max_length=255, null=True, blank=True)
    voltage = models.CharField("Voltage", max_length=255, null=True, blank=True)
    tolerance = models.CharField("Tolerance", max_length=255, null=True, blank=True)
    value_si = models.FloatField("значение в СИ", null=True, blank=True,
                                 help_text="для фильтров: 10k → 10000, 100nF → 1e-7")
    voltage_v = models.FloatField("напряжение, В", null=True, blank=True)
    tolerance_pct = models.FloatField("допуск, %", null=True, blank=True)

    datasheet_url = models.URLField("даташит (HelpURL)", max_length=2000, null=True, blank=True)
    status = models.CharField("статус", max_length=16, choices=Status.choices, default=Status.ACTIVE)

    created_at = models.DateTimeField("создан", db_default=Now(), editable=False)
    updated_at = models.DateTimeField("изменён", db_default=Now(), editable=False)

    class Meta:
        managed = False
        db_table = "components"
        constraints = [models.UniqueConstraint(fields=["manufacturer", "manufacturer_pn"],
                                               name="components_mpn_uq")]
        ordering = ["id"]
        verbose_name = "компонент"
        verbose_name_plural = "компоненты"

    def __str__(self):
        return f"{self.design_item_id or 'новый'} {self.manufacturer_pn}"

    def get_absolute_url(self):
        return reverse("library:component", args=[self.design_item_id])

    @property
    def altium_comment(self):
        return self.comment or self.value or self.manufacturer_pn


class ComponentFootprint(models.Model):
    id = models.BigAutoField(primary_key=True)
    component = models.ForeignKey(Component, models.CASCADE, related_name="footprint_slots")
    slot = models.PositiveSmallIntegerField("позиция", choices=FOOTPRINT_SLOTS)
    footprint = models.ForeignKey(Footprint, models.PROTECT, related_name="component_slots",
                                  verbose_name="посадочное место")

    class Meta:
        managed = False
        db_table = "component_footprints"
        ordering = ["slot"]
        verbose_name = "посадочное место компонента"
        verbose_name_plural = "посадочные места (1 — основное, 2..4 — альтернативные)"

    def __str__(self):
        return f"{self.slot}: {self.footprint}"

    @property
    def is_primary(self):
        return self.slot == 1


class ComponentSupplier(models.Model):
    id = models.BigAutoField(primary_key=True)
    component = models.ForeignKey(Component, models.CASCADE, related_name="supplier_slots")
    slot = models.PositiveSmallIntegerField("позиция", choices=SUPPLIER_SLOTS)
    supplier = models.ForeignKey(Supplier, models.PROTECT, related_name="component_slots",
                                 verbose_name="магазин")
    supplier_pn = models.CharField("артикул в магазине", max_length=255)
    product_url = models.URLField("ссылка на товар", max_length=2000, null=True, blank=True,
                                  help_text="Пусто — строится по шаблону магазина")

    class Meta:
        managed = False
        db_table = "component_suppliers"
        ordering = ["slot"]
        verbose_name = "магазин компонента"
        verbose_name_plural = "магазины (не более трёх)"

    def __str__(self):
        return f"{self.slot}: {self.supplier} {self.supplier_pn}"

    @property
    def url(self):
        if self.product_url:
            return self.product_url
        template = self.supplier.product_url_template
        return template.replace("{pn}", self.supplier_pn) if template else None
