"""SVG-превью символов и посадочных мест из файлов Altium (библиотека pyaltiumlib, MIT)
и проверка слоёв посадочных мест (pcb_checks).

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

from . import pcb_checks
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


def inspect_library(data: bytes, kind: str, names: list[str]) -> dict:
    """Один проход pyaltiumlib по файлу:
    {"previews": {имя: {"svg"} | {"error"}},                       — для первых MAX_PREVIEWS элементов
     "checks": {"library": [...], "footprints": {имя: [...]}} | None — только для .PcbLib, см. pcb_checks;
     "checks_error": "причина" — если проверку выполнить не удалось}"""
    result = {"previews": {}, "checks": None}
    try:
        # тип pyaltiumlib определяет по расширению имени файла
        library = pyaltiumlib.read("library.PcbLib" if kind == PCBLIB else "library.SchLib", io.BytesIO(data))
    except Exception as exc:
        reason = f"не удалось прочитать файл ({type(exc).__name__})"
        result["previews"] = {name: {"error": reason} for name in names}
        if kind == PCBLIB:
            result["checks_error"] = reason
        return result

    for name in names[:MAX_PREVIEWS]:
        result["previews"][name] = _render_one(library, name)

    if kind == PCBLIB:
        try:
            footprints = {}
            for name in names[:MAX_PREVIEWS]:
                try:
                    footprints[name] = pcb_checks.check_footprint(library, library.get_part(name))
                except Exception as exc:
                    footprints[name] = [f"Примитивы проверить не удалось ({type(exc).__name__})."]
            result["checks"] = {"library": pcb_checks.check_layers(library), "footprints": footprints}
        except Exception as exc:
            result["checks_error"] = f"не удалось проверить слои ({type(exc).__name__})"
    return result


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
