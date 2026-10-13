"""Пути к файлам библиотеки относительно .DbLib: symbols/<Категория>/<ИМЯ>.SchLib, footprints/<…>.PcbLib.

То же правило реализовано в static/library/library_path.js — для подсказки прямо в форме.
"""

import re

SYMBOLS = "symbols"
FOOTPRINTS = "footprints"


def normalize_library_path(value, root):
    """Приводит путь к виду '<root>/…': убирает кавычки и file://, '\\' → '/',
    отрезает всё до последней папки root ('symbols' или 'footprints', без учёта регистра).

    'D:\\Lib\\footprints\\Resistors\\R.PcbLib' → 'footprints/Resistors/R.PcbLib'.
    Путь без папки root возвращается нормализованным, но не обрезанным.
    """
    path = (value or "").strip()
    if len(path) >= 2 and path[0] == path[-1] and path[0] in "\"'":
        path = path[1:-1].strip()
    path = re.sub(r"^file:/*", "", path, flags=re.IGNORECASE)
    segments = [s for s in path.replace("\\", "/").split("/") if s and s != "."]
    lowered = [s.lower() for s in segments]
    if root in lowered:
        i = len(lowered) - 1 - lowered[::-1].index(root)
        segments = [root] + segments[i + 1:]
    return "/".join(segments)
