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
