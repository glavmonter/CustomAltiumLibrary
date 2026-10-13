from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.html import format_html

from .images import media_from_upload
from .models import (Component, ComponentClass, ComponentFootprint, ComponentSupplier, Footprint,
                     Manufacturer, Supplier, Symbol)
from .paths import FOOTPRINTS, SYMBOLS, normalize_library_path
from .widgets import ImageDropWidget, LibraryPathWidget


def image_tag(media_id, size=64, link=False):
    """Картинка из lib.media; link=True — по клику открывается в полном размере."""
    if not media_id:
        return "—"
    url = reverse("library:media", args=[media_id])
    img = format_html('<img src="{}" alt="" style="max-width:{}px;max-height:{}px;background:#fff;'
                      'vertical-align:top">', url, size, size)
    if link:
        return format_html('<a href="{}" target="_blank" rel="noopener" title="Открыть в полном размере">{}</a>',
                           url, img)
    return img


# ---------------------------------------------------------------------------
#  Картинки: загрузка файла в lib.media и привязка к символу / посадочному месту
# ---------------------------------------------------------------------------
class ImageUploadField(forms.FileField):
    widget = ImageDropWidget

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("help_text", "PNG, JPEG, WebP или SVG: перетащите файл, вставьте из буфера обмена "
                                       "(Ctrl+V) или выберите. Новая картинка заменяет текущую.")
        super().__init__(**kwargs)

    def clean(self, data, initial=None):
        upload = super().clean(data, initial)
        return media_from_upload(upload) if upload else None


class ImageUploadAdmin(admin.ModelAdmin):
    """Поля формы <name>_upload / <name>_clear управляют FK <name>_media."""

    image_fields = ()

    def save_model(self, request, obj, form, change):
        for name in self.image_fields:
            media = form.cleaned_data.get(f"{name}_upload")
            if media is not None:
                if media.pk is None:
                    media.save()
                setattr(obj, f"{name}_media", media)
            elif form.cleaned_data.get(f"{name}_clear"):
                setattr(obj, f"{name}_media", None)
        super().save_model(request, obj, form, change)


class SymbolForm(forms.ModelForm):
    preview_upload = ImageUploadField(label="Загрузить картинку УГО")
    preview_clear = forms.BooleanField(label="Удалить картинку", required=False)

    class Meta:
        model = Symbol
        fields = ["library_ref", "library_path"]
        widgets = {"library_path": LibraryPathWidget(SYMBOLS, ".SchLib", ref_field="library_ref")}

    def clean_library_path(self):
        return normalize_library_path(self.cleaned_data["library_path"], SYMBOLS)


class FootprintForm(forms.ModelForm):
    preview_upload = ImageUploadField(label="Загрузить 2D-вид")
    preview_clear = forms.BooleanField(label="Удалить 2D-вид", required=False)
    preview3d_upload = ImageUploadField(label="Загрузить 3D-вид")
    preview3d_clear = forms.BooleanField(label="Удалить 3D-вид", required=False)

    class Meta:
        model = Footprint
        fields = ["footprint_ref", "footprint_path", "description"]
        widgets = {"footprint_path": LibraryPathWidget(FOOTPRINTS, ".PcbLib", ref_field="footprint_ref")}

    def clean_footprint_path(self):
        return normalize_library_path(self.cleaned_data["footprint_path"], FOOTPRINTS)


@admin.register(Symbol)
class SymbolAdmin(ImageUploadAdmin):
    form = SymbolForm
    image_fields = ("preview",)
    list_display = ("thumbnail", "library_ref", "library_path", "updated_at")
    list_display_links = ("thumbnail", "library_ref")
    search_fields = ("library_ref", "library_path")
    readonly_fields = ("preview_image",)
    fields = ("library_ref", "library_path", "preview_image", "preview_upload", "preview_clear")

    @admin.display(description="УГО")
    def thumbnail(self, obj):
        return image_tag(obj.preview_media_id, 48)

    @admin.display(description="Текущая картинка")
    def preview_image(self, obj):
        return image_tag(obj.preview_media_id, 320)


@admin.register(Footprint)
class FootprintAdmin(ImageUploadAdmin):
    form = FootprintForm
    image_fields = ("preview", "preview3d")
    list_display = ("thumbnail", "footprint_ref", "footprint_path", "description")
    list_display_links = ("thumbnail", "footprint_ref")
    search_fields = ("footprint_ref", "footprint_path", "description")
    readonly_fields = ("preview_image", "preview3d_image")
    fields = ("footprint_ref", "footprint_path", "description",
              "preview_image", "preview_upload", "preview_clear",
              "preview3d_image", "preview3d_upload", "preview3d_clear")

    @admin.display(description="Вид")
    def thumbnail(self, obj):
        return image_tag(obj.preview_media_id, 48)

    @admin.display(description="Текущий 2D-вид")
    def preview_image(self, obj):
        return image_tag(obj.preview_media_id, 320)

    @admin.display(description="Текущий 3D-вид")
    def preview3d_image(self, obj):
        return image_tag(obj.preview3d_media_id, 320)


# ---------------------------------------------------------------------------
#  Справочники
# ---------------------------------------------------------------------------
@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ("name", "website")
    search_fields = ("name",)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "website", "product_url_template")
    search_fields = ("name",)


@admin.register(ComponentClass)
class ComponentClassAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "view_name", "designator_prefix", "sort_order")
    list_select_related = ("parent",)
    search_fields = ("name", "view_name")


# ---------------------------------------------------------------------------
#  Компонент
# ---------------------------------------------------------------------------
class SlotFormSet(forms.BaseInlineFormSet):
    """Повторы проверяются здесь: в БД ограничения отложенные (до COMMIT), чтобы слоты можно было менять местами."""

    distinct_fields = ("slot",)
    require_primary = False

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        seen = {name: set() for name in self.distinct_fields}
        for form in self.forms:
            data = getattr(form, "cleaned_data", None)
            if not data or data.get("DELETE"):
                continue
            for name in self.distinct_fields:
                value = data.get(name)
                if value in seen[name]:
                    raise ValidationError(f"«{form.fields[name].label}» повторяется: {value}")
                seen[name].add(value)
        if self.require_primary and seen["slot"] and 1 not in seen["slot"]:
            raise ValidationError("Не задано основное посадочное место (позиция 1).")


class FootprintSlotFormSet(SlotFormSet):
    distinct_fields = ("slot", "footprint")
    require_primary = True


class SupplierSlotFormSet(SlotFormSet):
    distinct_fields = ("slot", "supplier")


class ComponentFootprintInline(admin.TabularInline):
    model = ComponentFootprint
    formset = FootprintSlotFormSet
    extra = 1
    max_num = 4
    autocomplete_fields = ("footprint",)
    readonly_fields = ("preview_2d",)
    fields = ("slot", "footprint", "preview_2d")

    @admin.display(description="2D-вид")
    def preview_2d(self, obj):
        return image_tag(obj.footprint.preview_media_id if obj.footprint_id else None, 200, link=True)


class ComponentSupplierInline(admin.TabularInline):
    model = ComponentSupplier
    formset = SupplierSlotFormSet
    extra = 1
    max_num = 3
    autocomplete_fields = ("supplier",)
    fields = ("slot", "supplier", "supplier_pn", "product_url")


@admin.register(Component)
class ComponentAdmin(admin.ModelAdmin):
    list_display = ("design_item_id", "manufacturer_pn", "manufacturer", "component_class",
                    "value", "voltage", "tolerance", "status")
    list_display_links = ("design_item_id", "manufacturer_pn")
    list_filter = ("status", "component_class", "manufacturer")
    list_select_related = ("manufacturer", "component_class")
    search_fields = ("design_item_id", "manufacturer_pn", "description", "value", "comment")
    autocomplete_fields = ("component_class", "manufacturer", "symbol")
    readonly_fields = ("design_item_id", "symbol_preview", "created_at", "updated_at")
    save_as = True          # «Сохранить как новый» — удобно для серий номиналов
    save_on_top = True
    inlines = [ComponentFootprintInline, ComponentSupplierInline]
    fieldsets = (
        (None, {"fields": ("design_item_id", "status", "component_class")}),
        ("Производитель", {"fields": ("manufacturer", "manufacturer_pn", "datasheet_url")}),
        ("Параметры", {"fields": ("comment", "description", "value", "voltage", "tolerance")}),
        ("Числовые значения для фильтров", {"fields": ("value_si", "voltage_v", "tolerance_pct"),
                                            "classes": ("collapse",)}),
        ("Символ (УГО)", {"fields": ("symbol", "symbol_preview")}),
        ("Служебное", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Картинка УГО")
    def symbol_preview(self, obj):
        return image_tag(obj.symbol.preview_media_id if obj.symbol_id else None, 240, link=True)
