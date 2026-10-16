"""Проверка посадочных мест (.PcbLib) на соглашения о механических слоях.

Не блокирует добавление посадочного места — результат показывается как предупреждение.
Работает с библиотекой, уже прочитанной pyaltiumlib (см. altium_render.inspect_library).
"""

from collections import Counter

from pyaltiumlib.datatypes import PCBLayerKind

# Вид слоя → механический слой, на котором он должен быть в библиотеке
REQUIRED_LAYERS = {
    "TopAssembly": "Mechanical 21",
    "BottomAssembly": "Mechanical 22",
    "TopDesignator": "Mechanical 23",
    "BottomDesignator": "Mechanical 24",
    "TopComponentOutline": "Mechanical 27",
    "BottomComponentOutline": "Mechanical 28",
    "TopCourtyard": "Mechanical 15",
    "BottomCourtyard": "Mechanical 16",
    "Top3DBody": "Mechanical 13",
    "Bottom3DBody": "Mechanical 14",
}
# На этих слоях у посадочного места должен быть хотя бы один примитив
LAYERS_WITH_PRIMITIVES = ("TopCourtyard", "TopAssembly", "TopDesignator")
# На этих слоях примитивов быть не должно (контур платы задаётся в плате, а не в посадочном месте).
# Вид слоя → его механический слой: проверяются оба — слой с этим видом и сам механический слой,
# даже если вид с него сняли (иначе примитивы на «разжалованном» Mechanical 1 не видны).
LAYERS_WITHOUT_PRIMITIVES = {"BoardShape": "Mechanical 1"}
DESIGNATOR_LAYER = "TopDesignator"
DESIGNATOR_TEXT = ".designator"

# pyaltiumlib 0.7.1 не знает некоторые виды механических слоёв Altium; без них
# get_layer(kind="BoardShape") ничего не находит. Проверить при обновлении pyaltiumlib.
for _code, _name in ((0x1E, "BoardShape"), (0x10, "TopDimensions"), (0x11, "BottomDimensions")):
    PCBLayerKind._map.setdefault(_code, _name)


def check_layers(library) -> list[str]:
    """Слои библиотеки: каждый вид из REQUIRED_LAYERS назначен на свой механический слой."""
    problems = []
    for kind, mechanical in REQUIRED_LAYERS.items():
        layer = library.get_layer(kind=kind)
        if layer is None:
            problems.append(f"Слой {kind} не назначен (нужен {mechanical}).")
        elif layer.name != mechanical:
            problems.append(f"Слой {kind} на {layer.name}, а нужен {mechanical}.")
    return problems


def check_footprint(library, part) -> list[str]:
    """Примитивы посадочного места: обязательные слои не пустые, на запрещённых пусто,
    на TopDesignator есть строка .Designator."""
    kind_by_layer_id = {layer.id: str(layer.layer_type) for layer in library.Layers if layer.layer_type != 0}
    name_by_layer_id = {layer.id: layer.name for layer in library.Layers}
    primitives = Counter()
    forbidden = {kind: Counter() for kind in LAYERS_WITHOUT_PRIMITIVES}   # вид → {имя слоя: примитивов}
    designator_layers = []   # где лежат строки .Designator
    for record in part.Records:
        layer_id = getattr(record, "layer", None)
        kind = kind_by_layer_id.get(layer_id)
        if kind is not None:
            primitives[kind] += 1
        for forbidden_kind, mechanical in LAYERS_WITHOUT_PRIMITIVES.items():
            if kind == forbidden_kind or name_by_layer_id.get(layer_id) == mechanical:
                forbidden[forbidden_kind][name_by_layer_id.get(layer_id, "?")] += 1
        if (type(record).__name__ == "PcbString"
                and str(getattr(record, "text", "")).strip().lower() == DESIGNATOR_TEXT):
            designator_layers.append(kind or name_by_layer_id.get(layer_id, "?"))

    problems = []
    for kind, found in forbidden.items():
        for layer_name, count in found.items():
            problems.append(f"На слое {kind} ({layer_name}) {count} примитив(ов) — их быть не должно.")
    designator_missing = DESIGNATOR_LAYER not in designator_layers
    for kind in LAYERS_WITH_PRIMITIVES:
        if not primitives[kind] and not (kind == DESIGNATOR_LAYER and designator_missing):
            problems.append(f"На слое {kind} нет примитивов.")
    if designator_missing:
        elsewhere = f" (она на слое {', '.join(dict.fromkeys(designator_layers))})" if designator_layers else ""
        problems.append(f"На слое {DESIGNATOR_LAYER} нет строки .Designator{elsewhere}.")
    return problems
