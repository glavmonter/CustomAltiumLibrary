"""Приём загруженных картинок в lib.media."""

import hashlib
import io

from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

from .models import Media

RASTER_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


def _looks_like_svg(data: bytes) -> bool:
    head = data[:1024].lstrip().lower()
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:4096].lower())


def media_from_upload(upload) -> Media:
    """Проверяет файл и возвращает Media: существующую с тем же sha256 или новую (ещё не сохранённую)."""
    data = upload.read()
    if len(data) > settings.LIBRARY_MAX_IMAGE_BYTES:
        raise ValidationError(f"Файл больше {settings.LIBRARY_MAX_IMAGE_BYTES // (1024 * 1024)} МБ.")

    sha256 = hashlib.sha256(data).digest()
    existing = Media.objects.defer("data").filter(sha256=sha256).first()
    if existing:
        return existing

    width = height = None
    if _looks_like_svg(data):
        mime = "image/svg+xml"
    else:
        try:
            with Image.open(io.BytesIO(data)) as img:
                fmt = img.format
                width, height = img.size
        except (UnidentifiedImageError, OSError):
            fmt = None
        mime = RASTER_MIME.get(fmt)
        if mime is None:
            raise ValidationError("Поддерживаются PNG, JPEG, WebP и SVG.")

    return Media(sha256=sha256, mime_type=mime, data=data, width_px=width, height_px=height)
