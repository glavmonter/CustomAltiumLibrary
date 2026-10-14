"""SVG-превью символов и посадочных мест из файлов Altium (библиотека pyaltiumlib, MIT).

Рендер — подсказка, а не обязательный шаг: если pyaltiumlib не справилась с файлом
(известный случай — символы с именем длиннее 31 символа), возвращается причина,
и картинку выбирают вручную.
"""

import io
import logging
import re

import pyaltiumlib
import svgwrite
from pyaltiumlib.datatypes import parametercollection

from .altium_files import ANSI, PCBLIB

WIDTH, HEIGHT = 800, 600
MAX_PREVIEWS = 50
_PRIMITIVE = re.compile(r"<(line|rect|polygon|polyline|path|circle|ellipse|text)\b")

# pyaltiumlib пишет в лог о каждом неподдерживаемом примитиве («unsupported RecordID» и т. п.) —
# это шум в логах сервера; свои сбои рендера мы и так показываем пользователю
logging.getLogger("pyaltiumlib").setLevel(logging.CRITICAL)

# Обход ошибки pyaltiumlib 0.7.1: ParameterCollection.parse декодирует блоки строго как windows-1252
# и падает (UnboundLocalError), если в файле есть байты вне этой кодировки — например, русский текст
# в cp1251. Отдаём ей уже декодированную строку: Altium пишет текст в кодировке Windows (у нас cp1251),
# поэтому заодно русские надписи на картинках читаются. Проверить при обновлении pyaltiumlib.
_original_parse = parametercollection.ParameterCollection.parse


def _parse_ansi(self, data):
    if isinstance(data, (bytes, bytearray)):
        data = bytes(data).decode(ANSI, "replace")
    return _original_parse(self, data)


parametercollection.ParameterCollection.parse = _parse_ansi


def render_previews(data: bytes, kind: str, names: list[str]) -> dict:
    """{имя: {"svg": "<svg…>"} | {"error": "причина"}} для первых MAX_PREVIEWS элементов."""
    try:
        # тип pyaltiumlib определяет по расширению имени файла
        library = pyaltiumlib.read("library.PcbLib" if kind == PCBLIB else "library.SchLib", io.BytesIO(data))
    except Exception as exc:
        return {name: {"error": f"не удалось прочитать файл ({type(exc).__name__})"} for name in names}

    previews = {}
    for name in names[:MAX_PREVIEWS]:
        previews[name] = _render_one(library, name)
    return previews


def _render_one(library, name):
    try:
        part = library.get_part(name)
        drawing = svgwrite.Drawing(size=(WIDTH, HEIGHT), viewBox=f"0 0 {WIDTH} {HEIGHT}")
        part.draw_svg(drawing, WIDTH, HEIGHT)
        svg = drawing.tostring()
    except Exception as exc:
        return {"error": f"не удалось отрисовать ({type(exc).__name__})"}
    # фон рисуется всегда; если кроме него ничего нет — рендер пустой
    if len(_PRIMITIVE.findall(svg)) <= 1:
        return {"error": "pyaltiumlib не нашла графики элемента"}
    return {"svg": svg}
