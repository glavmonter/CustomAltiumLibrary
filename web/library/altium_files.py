"""Разбор файлов библиотек Altium: имена символов (.SchLib) и посадочных мест (.PcbLib).

Оба формата — OLE Compound File (CFB):
  .SchLib  поток FileHeader: |HEADER=…Schematic Library…|COMPCOUNT=N|LIBREF0=…|%UTF8%LIBREF0=…|…
           каждый символ — хранилище в корне (имя обрезано до 31 символа).
  .PcbLib  поток Library/Data: блок параметров, uint32 N, затем N блоков [uint32 размер][byte длина][имя].
           каждое посадочное место — хранилище в корне (имя обрезано до 31 символа).
Если главный источник не прочитался, имена берутся из хранилищ в корне.
"""

import io
import struct
from dataclasses import dataclass, field

import olefile

SCHLIB = "schlib"
PCBLIB = "pcblib"
KIND_TITLES = {SCHLIB: "библиотека символов (.SchLib)", PCBLIB: "библиотека посадочных мест (.PcbLib)"}

# Altium пишет текст в кодировке Windows системы; для русской Windows — cp1251.
# Значения с префиксом %UTF8% — в UTF-8.
ANSI = "cp1251"

# служебные хранилища в корне — не элементы библиотеки
SERVICE_STORAGES = {
    SCHLIB: {"filefooter", "fileheader", "storage", "sectionkeys", "additional"},
    PCBLIB: {"library", "fileversioninfo", "fileheader", "sectionkeys"},
}


class LibraryFileError(ValueError):
    """Файл не удалось разобрать; текст — для пользователя."""


@dataclass
class LibraryContents:
    kind: str                       # SCHLIB / PCBLIB
    names: list[str]                # символы или посадочные места, в порядке файла
    source: str                     # откуда взяты имена: header / storages
    warnings: list[str] = field(default_factory=list)
    descriptions: dict[str, str] = field(default_factory=dict)   # имя → Description из файла


def read_library(data: bytes) -> LibraryContents:
    if not olefile.isOleFile(io.BytesIO(data)):
        raise LibraryFileError("Файл не похож на библиотеку Altium (это не OLE-контейнер .SchLib/.PcbLib).")
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception as exc:  # повреждённый контейнер
        raise LibraryFileError(f"Не удалось открыть файл: {exc}") from exc
    with ole:
        if ole.exists("Library/Data"):
            kind, reader = PCBLIB, _pcblib_names
        elif ole.exists("FileHeader") and b"Schematic Library" in _read(ole, "FileHeader")[:200]:
            kind, reader = SCHLIB, _schlib_names
        else:
            raise LibraryFileError("Не удалось определить тип файла: нет ни FileHeader символов, ни Library/Data.")

        result = LibraryContents(kind=kind, names=[], source="header")
        try:
            result.names = reader(ole)
        except (struct.error, IndexError, ValueError, KeyError) as exc:
            result.warnings.append(f"Заголовок библиотеки не прочитан ({exc}), имена взяты из структуры файла.")
        if not result.names:
            result.names = _root_storages(ole, kind)
            result.source = "storages"
        try:
            found = (_schlib_descriptions if kind == SCHLIB else _pcblib_descriptions)(ole)
        except (struct.error, IndexError, ValueError, KeyError, OSError):
            found = {}   # описание — подсказка, без него разбор файла всё равно полезен
        result.descriptions = {name: found[name] for name in result.names if found.get(name)}
        return result


# ---------------------------------------------------------------------------
def _read(ole, path):
    with ole.openstream(path) as stream:
        return stream.read()


def _parameter_block(data, offset=0):
    """Блок параметров Altium: uint32 (младшие 24 бита — длина) + |KEY=VALUE|…\\0. → (dict, конец блока)"""
    length = struct.unpack_from("<I", data, offset)[0] & 0xFFFFFF
    raw = data[offset + 4: offset + 4 + length].split(b"\0", 1)[0]
    params = {}
    for item in raw.split(b"|"):
        key, sep, value = item.partition(b"=")
        if not sep:
            continue
        key = key.decode("ascii", "replace").upper()
        params[key] = value.decode("utf-8" if key.startswith("%UTF8%") else ANSI, "replace")
    return params, offset + 4 + length


def _schlib_names(ole):
    params, _ = _parameter_block(_read(ole, "FileHeader"))
    count = int(params.get("COMPCOUNT", "0"))
    names = []
    for i in range(count):
        name = params.get(f"%UTF8%LIBREF{i}") or params.get(f"LIBREF{i}")
        if name is None:
            raise KeyError(f"нет LIBREF{i}")
        names.append(name)
    return names


def _schlib_descriptions(ole):
    """FileHeader: COMPDESCR<i> (или %UTF8%COMPDESCR<i>) для символа LIBREF<i>."""
    params, _ = _parameter_block(_read(ole, "FileHeader"))
    descriptions = {}
    for i in range(int(params.get("COMPCOUNT", "0"))):
        name = params.get(f"%UTF8%LIBREF{i}") or params.get(f"LIBREF{i}")
        text = params.get(f"%UTF8%COMPDESCR{i}") or params.get(f"COMPDESCR{i}")
        if name and text:
            descriptions[name] = text
    return descriptions


def _pcblib_descriptions(ole):
    """<хранилище посадочного места>/Parameters: |PATTERN=<полное имя>|…|DESCRIPTION=…|.
    Сопоставляем по PATTERN, а не по имени хранилища: оно обрезано до 31 символа."""
    descriptions = {}
    for entry in ole.listdir(streams=True, storages=False):
        if len(entry) != 2 or entry[1] != "Parameters" or entry[0].lower() in SERVICE_STORAGES[PCBLIB]:
            continue
        params, _ = _parameter_block(_read(ole, "/".join(entry)))
        name = params.get("%UTF8%PATTERN") or params.get("PATTERN")
        text = params.get("%UTF8%DESCRIPTION") or params.get("DESCRIPTION")
        if name and text:
            descriptions[name] = text
    return descriptions


def _pcblib_names(ole):
    data = _read(ole, "Library/Data")
    _, offset = _parameter_block(data)
    count = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    if count > 100_000:
        raise ValueError(f"неправдоподобное число посадочных мест: {count}")
    names = []
    for _ in range(count):
        block = struct.unpack_from("<I", data, offset)[0]
        length = data[offset + 4]
        names.append(data[offset + 5: offset + 5 + length].decode(ANSI, "replace"))
        offset += 4 + block
    return names


def _root_storages(ole, kind):
    service = SERVICE_STORAGES[kind]
    names = []
    for entry in ole.listdir(streams=False, storages=True):
        if len(entry) == 1 and entry[0].lower() not in service:
            names.append(entry[0])
    return names
