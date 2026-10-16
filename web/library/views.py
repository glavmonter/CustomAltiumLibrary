from collections import defaultdict

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, HttpResponseNotModified, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from .altium_files import KIND_TITLES, PCBLIB, SCHLIB, LibraryFileError, read_library
from .altium_render import inspect_library
from .models import Component, ComponentClass, ComponentFootprint, Manufacturer, Media
from .paths import FOOTPRINTS, SYMBOLS

PAGE_SIZE = 50


class ClassTree:
    """Дерево классов целиком в памяти: классов немного, а нужны пути и потомки."""

    def __init__(self):
        self.by_id = {c.id: c for c in ComponentClass.objects.all()}
        self.children = defaultdict(list)
        for c in self.by_id.values():
            self.children[c.parent_id].append(c)
        for lst in self.children.values():
            lst.sort(key=lambda c: (c.sort_order, c.name))
        self.own_counts = dict(Component.objects.values_list("component_class").annotate(n=Count("id")))

    def descendants(self, class_id):
        """Сам класс и все вложенные."""
        result, stack = set(), [class_id]
        while stack:
            cid = stack.pop()
            if cid in result:
                continue
            result.add(cid)
            stack.extend(c.id for c in self.children.get(cid, ()))
        return result

    def path(self, class_id):
        names, seen = [], set()
        while class_id and class_id in self.by_id and class_id not in seen:
            seen.add(class_id)
            names.append(self.by_id[class_id].name)
            class_id = self.by_id[class_id].parent_id
        return " / ".join(reversed(names))

    def flat(self):
        """Обход в глубину: [{'cls', 'depth', 'count'}] для бокового меню."""
        rows = []

        def walk(parent_id, depth):
            for c in self.children.get(parent_id, ()):
                count = sum(self.own_counts.get(i, 0) for i in self.descendants(c.id))
                rows.append({"cls": c, "depth": depth, "count": count})
                walk(c.id, depth + 1)

        walk(None, 0)
        return rows


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@require_GET
def component_list(request):
    tree = ClassTree()
    qs = (Component.objects
          .select_related("manufacturer", "component_class", "symbol")
          .prefetch_related(Prefetch(
              "footprint_slots",
              queryset=ComponentFootprint.objects.filter(slot=1).select_related("footprint"),
              to_attr="primary_footprint_slots")))

    q = request.GET.get("q", "").strip()
    for word in q.split():
        qs = qs.filter(Q(design_item_id__icontains=word) | Q(manufacturer_pn__icontains=word)
                       | Q(description__icontains=word) | Q(value__icontains=word)
                       | Q(comment__icontains=word) | Q(manufacturer__name__icontains=word))

    class_id = _int_or_none(request.GET.get("class"))
    current_class = tree.by_id.get(class_id)
    if current_class:
        qs = qs.filter(component_class_id__in=tree.descendants(class_id))

    manufacturer_id = _int_or_none(request.GET.get("manufacturer"))
    if manufacturer_id:
        qs = qs.filter(manufacturer_id=manufacturer_id)

    status = request.GET.get("status", "")
    if status in Component.Status.values:
        qs = qs.filter(status=status)

    page = Paginator(qs.order_by("id"), PAGE_SIZE).get_page(request.GET.get("page"))
    for c in page.object_list:
        slots = c.primary_footprint_slots
        c.primary_footprint = slots[0].footprint if slots else None

    return render(request, "library/component_list.html", {
        "page": page,
        "q": q,
        "class_rows": tree.flat(),
        "total_count": sum(tree.own_counts.values()),
        "current_class": current_class,
        "current_class_path": tree.path(class_id) if current_class else "",
        "manufacturers": Manufacturer.objects.all(),
        "manufacturer_id": manufacturer_id,
        "statuses": Component.Status.choices,
        "status": status,
    })


@require_GET
def component_detail(request, design_item_id):
    component = get_object_or_404(
        Component.objects.select_related("manufacturer", "component_class", "symbol"),
        design_item_id=design_item_id)
    tree = ClassTree()
    return render(request, "library/component_detail.html", {
        "c": component,
        "class_path": tree.path(component.component_class_id),
        "footprints": list(component.footprint_slots.select_related("footprint")),
        "suppliers": list(component.supplier_slots.select_related("supplier")),
    })


@require_GET
def media(request, pk):
    """Картинка из lib.media. Содержимое записи не меняется, поэтому кэшируется навсегда."""
    item = get_object_or_404(Media.objects.only("sha256", "mime_type", "data"), pk=pk)
    etag = f'"{bytes(item.sha256).hex()}"'
    if request.headers.get("If-None-Match") == etag:
        response = HttpResponseNotModified()
    else:
        response = HttpResponse(bytes(item.data), content_type=item.mime_type)
    response["ETag"] = etag
    response["Cache-Control"] = "private, max-age=31536000, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    # SVG загружают пользователи — запрещаем в нём скрипты при открытии напрямую
    response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    return response


@require_POST
def analyze_library_file(request):
    """Разбор .SchLib / .PcbLib: имена символов или посадочных мест и их SVG-превью. Файл не сохраняется.

    Тело запроса — сам файл (application/octet-stream), а не форма: тогда Django не разбирает
    тело заранее, и слишком большой файл отклоняется по Content-Length, не будучи принятым.
    ?root=symbols|footprints — что ожидается. CSRF-токен — в заголовке X-CSRFToken.
    """
    if not (request.user.is_active and request.user.is_staff):
        return JsonResponse({"error": "Нужен вход в админку."}, status=403)

    limit = settings.LIBRARY_MAX_LIBRARY_FILE_BYTES
    too_big = JsonResponse({"error": f"Файл больше {limit // (1024 * 1024)} МБ."}, status=413)
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        declared = 0
    if declared > limit:
        return too_big
    data = request.read(limit + 1)
    if len(data) > limit:
        return too_big
    if not data:
        return JsonResponse({"error": "Файл пустой."}, status=400)

    try:
        contents = read_library(data)
    except LibraryFileError as exc:
        return JsonResponse({"error": str(exc)}, status=422)

    expected = {SYMBOLS: SCHLIB, FOOTPRINTS: PCBLIB}.get(request.GET.get("root"))
    if expected and contents.kind != expected:
        return JsonResponse({"error": f"Это {KIND_TITLES[contents.kind]}, а здесь нужна {KIND_TITLES[expected]}."},
                            status=422)
    return JsonResponse({"kind": contents.kind, "names": contents.names,
                         "source": contents.source, "warnings": contents.warnings,
                         "descriptions": contents.descriptions,
                         **inspect_library(data, contents.kind, contents.names)})
