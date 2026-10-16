"""Внешнее API для массового добавления компонентов (например, целого ряда резисторов).

Авторизация: ключ приложения (ApiKey, выдаётся в админке) в заголовке
    Authorization: Bearer alk_…      (или X-API-Key: alk_…)
API действует от имени владельца ключа и с его правами в админке.

    GET  /api/v1/openapi.yaml        спецификация OpenAPI 3.1 (без ключа) — library/openapi.yaml
    GET  /api/v1/references/         справочники: классы, производители, магазины, символы, посадочные места
    GET  /api/v1/components/         поиск заведённых компонентов (?manufacturer=&mpn=&design_item_id=)
    POST /api/v1/components/bulk/    массовое добавление / обновление — см. bulk_components

Символы, посадочные места, классы, производители и магазины API не создаёт — только ссылается на них.
"""

import json
from datetime import timedelta
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from .models import (ApiKey, Component, ComponentClass, ComponentFootprint, ComponentSupplier, Footprint,
                     Manufacturer, Supplier, Symbol)

MAX_FOOTPRINTS, MAX_SUPPLIERS = 4, 3
SCALAR_FIELDS = ("comment", "description", "value", "voltage", "tolerance", "value_si", "voltage_v",
                 "tolerance_pct", "datasheet_url", "status")
NUMERIC_FIELDS = ("value_si", "voltage_v", "tolerance_pct")
ITEM_FIELDS = {"manufacturer", "manufacturer_pn", "class", "symbol", "footprints", "suppliers", *SCALAR_FIELDS}


def _json(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


def _error(status, message, **extra):
    return _json({"error": message, **extra}, status=status)


# ---------------------------------------------------------------------------
#  Авторизация по ключу приложения
# ---------------------------------------------------------------------------
def _raw_key(request):
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.headers.get("X-API-Key", "").strip()


def api_view(*methods):
    """JSON-эндпоинт с авторизацией по ApiKey: без CSRF и без сессии, request.api_key / request.api_user."""
    def decorator(view):
        @csrf_exempt
        @login_not_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                response = _error(405, f"Метод {request.method} не поддерживается.")
                response["Allow"] = ", ".join(methods)
                return response
            key = ApiKey.find(_raw_key(request))
            if key is None:
                response = _error(401, "Нужен действующий ключ API: заголовок Authorization: Bearer <ключ>.")
                response["WWW-Authenticate"] = 'Bearer realm="altium-library"'
                return response
            now = timezone.now()
            if not key.is_active or (key.expires_at and key.expires_at <= now) or not key.user.is_active:
                return _error(401, "Ключ API отключён или истёк.")
            if not key.last_used_at or now - key.last_used_at > timedelta(minutes=1):
                ApiKey.objects.filter(pk=key.pk).update(last_used_at=now)
            request.api_key, request.api_user = key, key.user
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def _require(request, *perms):
    missing = [p for p in perms if not request.api_user.has_perm(p)]
    if missing:
        return _error(403, f"У владельца ключа нет прав: {', '.join(missing)}.")
    return None


OPENAPI_SPEC = Path(__file__).with_name("openapi.yaml")


@login_not_required
@require_GET
def openapi_spec(request):
    """Спецификация API — без ключа: секретов в ней нет, её читают клиенты и генераторы кода."""
    return HttpResponse(OPENAPI_SPEC.read_bytes(), content_type="application/yaml; charset=utf-8")


# ---------------------------------------------------------------------------
#  Справочники
# ---------------------------------------------------------------------------
def _class_paths():
    classes = {c.id: c for c in ComponentClass.objects.all()}
    paths = {}
    for cid in classes:
        names, seen, current = [], set(), cid
        while current in classes and current not in seen:
            seen.add(current)
            names.append(classes[current].name)
            current = classes[current].parent_id
        paths[cid] = " / ".join(reversed(names))
    return classes, paths


@api_view("GET")
def references(request):
    denied = _require(request, "library.view_component")
    if denied:
        return denied
    classes, paths = _class_paths()
    return _json({
        "classes": [{"id": c.id, "name": c.name, "path": paths[c.id], "altium_table": c.view_name}
                    for c in sorted(classes.values(), key=lambda c: paths[c.id])],
        "manufacturers": [{"id": m.id, "name": m.name} for m in Manufacturer.objects.all()],
        "suppliers": [{"id": s.id, "name": s.name} for s in Supplier.objects.all()],
        "symbols": [{"id": s.id, "ref": s.library_ref, "path": s.library_path} for s in Symbol.objects.all()],
        "footprints": [{"id": f.id, "ref": f.footprint_ref, "path": f.footprint_path, "description": f.description}
                       for f in Footprint.objects.all()],
        "statuses": [value for value, _ in Component.Status.choices],
    })


# ---------------------------------------------------------------------------
#  Поиск компонентов
# ---------------------------------------------------------------------------
def _component_json(c, paths):
    return {
        "design_item_id": c.design_item_id,
        "manufacturer": c.manufacturer.name,
        "manufacturer_pn": c.manufacturer_pn,
        "class": paths.get(c.component_class_id),
        "symbol": {"ref": c.symbol.library_ref, "path": c.symbol.library_path},
        "footprints": [{"ref": s.footprint.footprint_ref, "path": s.footprint.footprint_path}
                       for s in c.footprint_slots.all()],
        "suppliers": [{"supplier": s.supplier.name, "pn": s.supplier_pn, "url": s.product_url}
                      for s in c.supplier_slots.all()],
        **{name: getattr(c, name) for name in SCALAR_FIELDS},
        # numeric из PostgreSQL приходит как Decimal, а JSON-кодировщик Django пишет его строкой
        **{name: float(getattr(c, name)) if getattr(c, name) is not None else None for name in NUMERIC_FIELDS},
    }


@api_view("GET")
def components(request):
    denied = _require(request, "library.view_component")
    if denied:
        return denied
    qs = (Component.objects.select_related("manufacturer", "symbol")
          .prefetch_related("footprint_slots__footprint", "supplier_slots__supplier").order_by("id"))
    if request.GET.get("manufacturer"):
        qs = qs.filter(manufacturer__name__iexact=request.GET["manufacturer"])
    if request.GET.get("mpn"):
        qs = qs.filter(manufacturer_pn__iexact=request.GET["mpn"])
    if request.GET.get("mpn_contains"):
        qs = qs.filter(manufacturer_pn__icontains=request.GET["mpn_contains"])
    if request.GET.get("design_item_id"):
        qs = qs.filter(design_item_id=request.GET["design_item_id"])
    try:
        limit = min(max(int(request.GET.get("limit", 100)), 1), 500)
        offset = max(int(request.GET.get("offset", 0)), 0)
    except ValueError:
        return _error(400, "limit и offset должны быть числами.")
    _, paths = _class_paths()
    total = qs.count()
    return _json({"count": total, "limit": limit, "offset": offset,
                  "results": [_component_json(c, paths) for c in qs[offset:offset + limit]]})


# ---------------------------------------------------------------------------
#  Массовое добавление
# ---------------------------------------------------------------------------
class _Lookup:
    """Справочники в памяти — один запрос на таблицу на весь пакет."""

    def __init__(self):
        self.classes, self.class_paths = _class_paths()
        self.manufacturers = {m.name.lower(): m for m in Manufacturer.objects.all()}
        self.suppliers = {s.name.lower(): s for s in Supplier.objects.all()}
        self.symbols = list(Symbol.objects.all())
        self.footprints = list(Footprint.objects.all())

    def component_class(self, ref):
        if isinstance(ref, int):
            return self.classes.get(ref) or f"класс с id={ref} не найден"
        text = str(ref).strip()
        if "/" in text:   # путь «Passive / Resistor» — пробелы вокруг «/» не важны
            wanted = " / ".join(part.strip() for part in text.split("/")).lower()
            by_path = [c for cid, c in self.classes.items() if self.class_paths[cid].lower() == wanted]
            return by_path[0] if by_path else f"класс «{text}» не найден"
        by_name = [c for c in self.classes.values() if c.name.lower() == text.lower()]
        if len(by_name) == 1:
            return by_name[0]
        if by_name:
            options = "; ".join(self.class_paths[c.id] for c in by_name)
            return f"класс «{text}» неоднозначен, укажите путь: {options}"
        return f"класс «{text}» не найден"

    def _library_item(self, ref, items, ref_attr, path_attr, what):
        """Символ / посадочное место: "REF", {"ref": "REF", "path": "…"} или {"id": 1}."""
        if isinstance(ref, dict) and "id" in ref:
            found = [i for i in items if i.id == ref["id"]]
            return found[0] if found else f"{what} с id={ref['id']} не найдено"
        if isinstance(ref, dict):
            name, path = ref.get("ref"), ref.get("path")
        else:
            name, path = ref, None
        if not isinstance(name, str) or not name.strip():
            return f"{what}: нужна строка с именем или {{\"ref\": …, \"path\": …}}"
        found = [i for i in items if getattr(i, ref_attr) == name.strip()
                 and (path is None or getattr(i, path_attr) == path)]
        if len(found) == 1:
            return found[0]
        if not found:
            return f"{what} «{name}»{f' в {path}' if path else ''} не найдено — сначала заведите его на сайте"
        paths = "; ".join(getattr(i, path_attr) for i in found)
        return f"{what} «{name}» есть в нескольких файлах, укажите path: {paths}"

    def symbol(self, ref):
        return self._library_item(ref, self.symbols, "library_ref", "library_path", "символ")

    def footprint(self, ref):
        return self._library_item(ref, self.footprints, "footprint_ref", "footprint_path", "посадочное место")


def _resolve(item, lookup, errors):
    """Ссылки элемента → объекты. Ошибки — в errors (строки)."""
    resolved = {}
    if "manufacturer" in item:
        m = lookup.manufacturers.get(str(item["manufacturer"]).strip().lower())
        if m is None:
            errors.append(f"производитель «{item['manufacturer']}» не найден — сначала заведите его на сайте")
        resolved["manufacturer"] = m
    if "class" in item:
        c = lookup.component_class(item["class"])
        if isinstance(c, str):
            errors.append(c)
        resolved["component_class"] = c if not isinstance(c, str) else None
    if "symbol" in item:
        s = lookup.symbol(item["symbol"])
        if isinstance(s, str):
            errors.append(s)
        resolved["symbol"] = s if not isinstance(s, str) else None
    if "footprints" in item:
        refs = item["footprints"]
        if not isinstance(refs, list) or len(refs) > MAX_FOOTPRINTS:
            errors.append(f"footprints: список, не больше {MAX_FOOTPRINTS} (первое — основное)")
            refs = []
        found = []
        for ref in refs:
            f = lookup.footprint(ref)
            if isinstance(f, str):
                errors.append(f)
            elif f in found:
                errors.append(f"посадочное место «{f.footprint_ref}» указано дважды")
            else:
                found.append(f)
        resolved["footprints"] = found
    if "suppliers" in item:
        rows = item["suppliers"]
        if not isinstance(rows, list) or len(rows) > MAX_SUPPLIERS:
            errors.append(f"suppliers: список, не больше {MAX_SUPPLIERS}")
            rows = []
        found = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("supplier") or not row.get("pn"):
                errors.append('suppliers: каждый элемент — {"supplier": "<магазин>", "pn": "<артикул>", "url": …}')
                continue
            s = lookup.suppliers.get(str(row["supplier"]).strip().lower())
            if s is None:
                errors.append(f"магазин «{row['supplier']}» не найден — сначала заведите его на сайте")
            elif any(s == x[0] for x in found):
                errors.append(f"магазин «{s.name}» указан дважды")
            else:
                found.append((s, str(row["pn"]).strip(), row.get("url") or None))
        resolved["suppliers"] = found
    return resolved


@api_view("POST")
def bulk_components(request):
    """Массовое добавление компонентов. Тело (JSON):

        {
          "mode": "create" | "upsert",   create (по умолчанию): MPN уже есть — ошибка;
                                         upsert: существующие (производитель + MPN) обновляются
          "dry_run": false,              true — только проверить, ничего не записывая
          "defaults": {…},               общие поля для всех компонентов (производитель, класс, символ…)
          "components": [
            {"manufacturer_pn": "CRCW0603100KFKEA", "value": "100k", "tolerance": "1%", …},
            …
          ]
        }

    Поля компонента: manufacturer, manufacturer_pn, class, symbol, footprints (до 4, первое — основное),
    suppliers (до 3: {"supplier", "pn", "url"}), comment, description, value, voltage, tolerance,
    value_si, voltage_v, tolerance_pct, datasheet_url, status.
    Ссылки: class — имя или путь «A / B»; symbol / footprint — имя, {"ref", "path"} или {"id"}.

    Всё или ничего: при любой ошибке ничего не записывается, в ответе — ошибки по каждому компоненту.
    """
    limit = settings.LIBRARY_API_MAX_BODY_BYTES
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        declared = 0
    if declared > limit:
        return _error(413, f"Тело запроса больше {limit // (1024 * 1024)} МБ — разбейте на несколько запросов.")
    raw = request.read(limit + 1)
    if len(raw) > limit:
        return _error(413, f"Тело запроса больше {limit // (1024 * 1024)} МБ — разбейте на несколько запросов.")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _error(400, f"Некорректный JSON: {exc}")
    if not isinstance(body, dict) or not isinstance(body.get("components"), list):
        return _error(400, 'Ожидается объект {"components": [...]}.')

    mode = body.get("mode", "create")
    if mode not in ("create", "upsert"):
        return _error(400, 'mode: "create" или "upsert".')
    perms = ["library.add_component"] + (["library.change_component"] if mode == "upsert" else [])
    denied = _require(request, *perms)
    if denied:
        return denied
    defaults = body.get("defaults") or {}
    items = body["components"]
    if not isinstance(defaults, dict):
        return _error(400, "defaults: объект с общими полями.")
    if not items:
        return _error(400, "components: пустой список.")
    if len(items) > settings.LIBRARY_API_MAX_ITEMS:
        return _error(413, f"Не больше {settings.LIBRARY_API_MAX_ITEMS} компонентов за запрос.")
    unknown = set(defaults) - ITEM_FIELDS - {"manufacturer_pn"}
    if unknown or "manufacturer_pn" in defaults:
        return _error(400, f"defaults: недопустимые поля {sorted(unknown | ({'manufacturer_pn'} & set(defaults)))}.")

    lookup = _Lookup()
    # существующие компоненты пакета: (производитель, MPN) → Component
    mpns = {str(i.get("manufacturer_pn", "")).strip() for i in items if isinstance(i, dict)}
    # MPN сравнивается с учётом регистра — как в уникальном ограничении БД
    existing = {(c.manufacturer_id, c.manufacturer_pn): c for c in Component.objects.filter(manufacturer_pn__in=mpns)}

    plans, results, seen = [], [], {}
    for index, item in enumerate(items):
        errors = []
        if not isinstance(item, dict):
            results.append({"index": index, "errors": ["элемент должен быть объектом"]})
            continue
        data = {**defaults, **item}
        unknown = set(data) - ITEM_FIELDS
        if unknown:
            errors.append(f"неизвестные поля: {', '.join(sorted(unknown))}")
        mpn = str(data.get("manufacturer_pn") or "").strip()
        if not mpn:
            errors.append("нет manufacturer_pn")
        resolved = _resolve(data, lookup, errors)
        manufacturer = resolved.get("manufacturer")
        if "manufacturer" not in data:
            errors.append("нет manufacturer")

        current = existing.get((manufacturer.id, mpn)) if manufacturer and mpn else None
        action = "update" if current else "create"
        if current and mode == "create":
            errors.append(f"компонент уже есть: {current.design_item_id} — используйте mode=upsert")
        if action == "create":
            for name in ("class", "symbol"):
                if name not in data:
                    errors.append(f"нет {name} (обязателен для нового компонента)")
        key = (manufacturer.id if manufacturer else None, mpn)
        if mpn and key in seen:
            errors.append(f"MPN «{mpn}» повторяется в запросе (элемент {seen[key]})")
        seen.setdefault(key, index)

        component = current or Component()
        if not errors:
            component.manufacturer = manufacturer
            component.manufacturer_pn = mpn
            for name in ("component_class", "symbol"):
                if resolved.get(name):
                    setattr(component, name, resolved[name])
            for name in SCALAR_FIELDS:
                if name in data:
                    setattr(component, name, data[name] if data[name] != "" else None)
            try:
                # типы, URL, статус. Ссылки и уникальность уже проверены по справочникам —
                # исключаем их, иначе full_clean делает запрос в БД на каждый внешний ключ
                component.full_clean(exclude=["design_item_id", "created_at", "updated_at",
                                              "manufacturer", "component_class", "symbol"],
                                     validate_unique=False, validate_constraints=False)
            except ValidationError as exc:
                errors.extend(f"{field}: {' '.join(messages)}" for field, messages in exc.message_dict.items())

        result = {"index": index, "manufacturer_pn": mpn, "action": action}
        if errors:
            result["errors"] = errors
        else:
            plans.append((index, action, component, resolved))
        results.append(result)

    failed = [r for r in results if r.get("errors")]
    if failed:
        return _error(400, f"Ошибки в {len(failed)} из {len(items)} компонентов — ничего не записано.",
                      results=results)
    if body.get("dry_run"):
        return _json({"dry_run": True, "created": sum(p[1] == "create" for p in plans),
                      "updated": sum(p[1] == "update" for p in plans), "results": results})

    with transaction.atomic():
        created, updated = [], []
        for index, action, component, resolved in plans:
            component.save()
            (created if action == "create" else updated).append(component.pk)
            if "footprints" in resolved:
                ComponentFootprint.objects.filter(component=component).delete()
                ComponentFootprint.objects.bulk_create(
                    ComponentFootprint(component=component, slot=slot, footprint=f)
                    for slot, f in enumerate(resolved["footprints"], 1))
            if "suppliers" in resolved:
                ComponentSupplier.objects.filter(component=component).delete()
                ComponentSupplier.objects.bulk_create(
                    ComponentSupplier(component=component, slot=slot, supplier=s, supplier_pn=pn, product_url=url)
                    for slot, (s, pn, url) in enumerate(resolved["suppliers"], 1))
        note = f"Через API, ключ «{request.api_key.name}»"
        for ids, flag in ((created, ADDITION), (updated, CHANGE)):
            if ids:
                LogEntry.objects.log_actions(request.api_user.pk, Component.objects.filter(pk__in=ids), flag,
                                             change_message=note, single_object=False)

    ids = {c.pk: c.design_item_id for c in Component.objects.filter(pk__in=created + updated)}
    for (index, action, component, _), result in zip(plans, results):
        result["design_item_id"] = ids[component.pk]
    return _json({"created": len(created), "updated": len(updated), "results": results},
                 status=201 if created else 200)
