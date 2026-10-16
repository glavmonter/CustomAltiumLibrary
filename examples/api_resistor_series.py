"""Пример клиента внешнего API: ряд чип-резисторов Vishay CRCW одним запросом.

Символ, посадочное место, класс, производитель и магазины должны быть заведены на сайте заранее —
API на них только ссылается. Ключ API выпускается в админке: «Ключи API» → «Добавить».

    set ALTIUM_LIBRARY_API_KEY=alk_…
    python api_resistor_series.py --series E24 --decades 1 2 3 4 5          # только проверка (dry_run)
    python api_resistor_series.py --series E24 --decades 1 2 3 4 5 --apply  # записать

Без зависимостей — только стандартная библиотека Python 3.9+.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from decimal import Decimal

E24 = [10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27, 30, 33, 36, 39, 43, 47, 51, 56, 62, 68, 75, 82, 91]
E96 = [100, 102, 105, 107, 110, 113, 115, 118, 121, 124, 127, 130, 133, 137, 140, 143, 147, 150, 154, 158,
       162, 165, 169, 174, 178, 182, 187, 191, 196, 200, 205, 210, 215, 221, 226, 232, 237, 243, 249, 255,
       261, 267, 274, 280, 287, 294, 301, 309, 316, 324, 332, 340, 348, 357, 365, 374, 383, 392, 402, 412,
       422, 432, 442, 453, 464, 475, 487, 499, 511, 523, 536, 549, 562, 576, 590, 604, 619, 634, 649, 665,
       681, 698, 715, 732, 750, 768, 787, 806, 825, 845, 866, 887, 909, 931, 953, 976]
UNITS = ((Decimal(10) ** 6, "M"), (Decimal(10) ** 3, "K"), (Decimal(1), "R"))


def series_values(series, decades):
    """Номиналы в омах: decades — порядки (0: 1–9.76 Ом, 1: 10–97.6 Ом, …, 5: 100k–976k)."""
    base = E24 if series == "E24" else E96
    scale = Decimal(10) if series == "E24" else Decimal(100)   # E24 записан как 10–91, E96 — как 100–976
    return [Decimal(v) / scale * Decimal(10) ** d for d in decades for v in base]


def vishay_code(ohms):
    """Код номинала Vishay CRCW: 4 знака, буква на месте запятой: 4R70, 47R0, 470R, 4K70, 47K0, 470K, 4M70."""
    unit, letter = next((u, l) for u, l in UNITS if ohms >= u)
    value = ohms / unit
    whole = int(value)
    if value >= 100:
        return f"{whole}{letter}"
    if value >= 10:
        return f"{whole}{letter}{int((value - whole) * 10)}"
    return f"{whole}{letter}{int((value - whole) * 100):02d}"


def display_value(ohms):
    """Value для Altium: 4.7, 47, 470, 4.7k, 47k, 470k, 4.7M."""
    unit, letter = next((u, l) for u, l in UNITS if ohms >= u)
    text = format((ohms / unit).normalize(), "f")
    return text + {"R": "", "K": "k", "M": "M"}[letter]


def build_request(args):
    components = []
    for ohms in series_values(args.series, args.decades):
        code = vishay_code(ohms)
        components.append({
            "manufacturer_pn": f"{args.family}{code}{args.tolerance_code}{args.packaging}",
            "value": display_value(ohms),
            "value_si": float(ohms),
            "suppliers": [{"supplier": args.supplier, "pn": f"{args.family}{code}{args.tolerance_code}{args.packaging}"}]
            if args.supplier else [],
        })
    return {
        "mode": "upsert" if args.upsert else "create",
        "dry_run": not args.apply,
        "defaults": {
            "manufacturer": args.manufacturer,
            "class": args.component_class,
            "symbol": args.symbol,
            "footprints": [args.footprint],
            "voltage": args.voltage,
            "tolerance": args.tolerance,
            "tolerance_pct": float(args.tolerance.rstrip("%")),
            "description": args.description,
            "datasheet_url": args.datasheet,
        },
        "components": components,
    }


def post(url, key, body):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=os.environ.get("ALTIUM_LIBRARY_URL", "http://localhost:8000"))
    parser.add_argument("--series", choices=["E24", "E96"], default="E24")
    parser.add_argument("--decades", type=int, nargs="+", default=[1, 2, 3, 4, 5],
                        help="0: 1–9.76 Ом … 5: 100k–976k (по умолчанию 1–5: 10 Ом … 910k)")
    parser.add_argument("--family", default="CRCW0603", help="серия и типоразмер в MPN")
    parser.add_argument("--tolerance-code", default="F", help="F = 1%%")
    parser.add_argument("--packaging", default="KEA", help="TCR и упаковка в MPN")
    parser.add_argument("--tolerance", default="1%")
    parser.add_argument("--voltage", default="75V")
    parser.add_argument("--manufacturer", default="Vishay")
    parser.add_argument("--class", dest="component_class", default="Резисторы", help="имя или путь «A / B»")
    parser.add_argument("--symbol", default="STD_RES")
    parser.add_argument("--footprint", default="RESC1608X50AN")
    parser.add_argument("--supplier", default="", help="магазин, если артикул в нём совпадает с MPN")
    parser.add_argument("--description", default="Thick Film Chip Resistor 0603 1% 75V")
    parser.add_argument("--datasheet", default="https://www.vishay.com/docs/20035/dcrcwe3.pdf")
    parser.add_argument("--upsert", action="store_true", help="обновлять уже заведённые MPN")
    parser.add_argument("--apply", action="store_true", help="записать (без флага — только проверка)")
    args = parser.parse_args()

    key = os.environ.get("ALTIUM_LIBRARY_API_KEY")
    if not key:
        sys.exit("Задайте ключ API в переменной ALTIUM_LIBRARY_API_KEY")

    body = build_request(args)
    status, data = post(f"{args.url.rstrip('/')}/api/v1/components/bulk/", key, body)
    if status >= 400:
        print(f"Ошибка {status}: {data.get('error')}")
        for result in data.get("results", []):
            if result.get("errors"):
                print(f"  #{result['index']} {result.get('manufacturer_pn')}: {'; '.join(result['errors'])}")
        sys.exit(1)
    verb = "Будет" if data.get("dry_run") else "Готово"
    print(f"{verb}: создано {data['created']}, обновлено {data['updated']} из {len(body['components'])}.")
    for result in data["results"][:5]:
        print(f"  {result.get('design_item_id', '—')}  {result['manufacturer_pn']}  ({result['action']})")
    if not args.apply:
        print("Это была проверка. Чтобы записать, добавьте --apply.")


if __name__ == "__main__":
    main()
