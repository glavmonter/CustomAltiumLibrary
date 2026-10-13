from django import forms

IMAGE_ACCEPT = "image/png,image/jpeg,image/webp,image/svg+xml"


class ImageDropWidget(forms.FileInput):
    """Поле файла с зоной перетаскивания и вставкой картинки из буфера обмена (Ctrl+V).

    Файл всё равно уходит обычным <input type="file">, серверная часть не меняется.
    """

    template_name = "library/widgets/image_drop.html"

    class Media:
        css = {"all": ["library/image_drop.css"]}
        js = ["library/image_drop.js"]

    def __init__(self, attrs=None):
        super().__init__({"accept": IMAGE_ACCEPT, **(attrs or {})})


class LibraryPathWidget(forms.TextInput):
    """Поле Library Path / Footprint Path: принимает перетащенный файл библиотеки или вставленный путь
    и обрезает его до root ('symbols' / 'footprints'). Заполняет пустое поле ref_field именем элемента."""

    template_name = "library/widgets/library_path.html"

    class Media:
        css = {"all": ["library/library_path.css"]}
        js = ["library/library_path.js"]

    def __init__(self, root, extension, ref_field, attrs=None):
        self.root, self.extension, self.ref_field = root, extension, ref_field
        super().__init__({"class": "vTextField", "autocomplete": "off", "spellcheck": "false", **(attrs or {})})

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"].update(root=self.root, extension=self.extension, ref_field=self.ref_field)
        return context
