# Библиотека компонентов Altium Designer

Одна база PostgreSQL со сквозным Design Item ID для всех классов компонентов,
Altium Designer подключается к ней через DbLib/ODBC, редактирование и просмотр — через сайт на Django.

```
docker-compose.yml               db (PostgreSQL 18) + migrate (схема) + web (Django + gunicorn)
docker/db/10_roles.sh            роли и пароли из .env, первый запуск на пустом томе
web/library/migrations/          ЕДИНСТВЕННЫЙ источник схемы БД
web/library/migrations/sql/      SQL этих миграций (0001_initial.sql — начальная схема)
web/library/models.py            модели Django поверх схемы lib (managed = False)
```

## Запуск

```sh
cp .env.example .env      # поменять пароли и DJANGO_SECRET_KEY
docker compose up -d --build
```

Порядок старта: `db` → `migrate` (применяет новые миграции и завершается) → `web`.

- Сайт: http://localhost:8000, редактирование — http://localhost:8000/admin/
  (администратор из `DJANGO_SUPERUSER_*` создаётся при первом старте).
- Altium: PostgreSQL на порту `PG_PORT` (5432), пользователь `altium_reader`.
  Таблицы для DbLib — представления схемы `altium`, по одному на каждый класс с заполненным
  «вкладка в Altium» (включает подклассы). `altium.all_components` в DbLib не подключать: Altium путает
  компоненты, если они одновременно есть и в ней, и во вкладке класса. Она нужна сайту, DBeaver и отчётам.

Пересоздать БД с нуля (**все данные будут удалены**): `docker compose down -v && docker compose up -d`.

### Смена паролей после первого запуска

Пароли из `.env` записываются в базу только при первом запуске на пустом томе. Если поменять их потом,
`migrate`/`web` упадут с `password authentication failed`. Синхронизировать без потери данных:

```sh
docker compose up -d db
docker compose exec db sh /docker-entrypoint-initdb.d/10_roles.sh
docker compose up -d
```

(в Git Bash на Windows перед `docker compose exec` добавьте `MSYS_NO_PATHCONV=1`).
Администратор сайта создаётся из `DJANGO_SUPERUSER_*` тоже один раз; его пароль меняется
в админке или командой `docker compose exec web python manage.py changepassword admin`.

## Роли

| роль | кто | права |
|---|---|---|
| `library_owner` | сервис `migrate` | владелец базы, схем `lib`/`altium` и таблиц Django; DDL |
| `library_web` | сайт | чтение/запись данных, без DDL |
| `altium_reader` | Altium Designer | только чтение представлений `altium.*` |

Роли кластерные, поэтому их создаёт `docker/db/10_roles.sh`, а не миграции.
Без Docker создайте их вручную до первого `migrate` — миграция 0001 проверит, что они есть.

## Как менять схему

Всё — новой миграцией в `web/library/migrations/`; применённые миграции и их SQL-файлы не редактируются.

1. SQL изменения — в `web/library/migrations/sql/0002_<что>.sql`.
2. Миграция `web/library/migrations/0002_<что>.py`:

   ```python
   from django.db import migrations

   from library.schema_sql import run_sql_file


   class Migration(migrations.Migration):
       dependencies = [("library", "0001_initial")]
       operations = [
           run_sql_file("0002_<что>.sql", reverse_sql="...SQL отката..."),  # или имя .sql-файла
       ]
   ```

3. Поправить `models.py`, если менялись таблицы `lib.*`, и, при необходимости, представления `altium.*`.
   `makemigrations` изменения полей неуправляемых моделей не отслеживает — дополнительных операций не нужно.
4. `docker compose up -d --build` — сервис `migrate` применит миграцию.

Новые таблицы в `lib` и `altium` получают права для `library_web` / `altium_reader` автоматически
(`ALTER DEFAULT PRIVILEGES` в 0001), если создаются под `library_owner`.

## Внешнее API: массовое добавление компонентов

Для серий (например, весь ряд резисторов Vishay): символ, посадочные места, класс, производитель и
магазины заводятся на сайте заранее, а компоненты с разными номиналами и допусками добавляются через API.
Код — `web/library/api.py`, пример клиента — `examples/api_resistor_series.py`.
Спецификация OpenAPI 3.1 — `web/library/openapi.yaml`, сервер отдаёт её без ключа по адресу
`/api/v1/openapi.yaml` (для Swagger UI, Postman, генераторов клиентов). При изменении `api.py` её нужно обновлять.

**Ключ.** Админка → «Ключи API» → «Добавить». Ключ показывается **один раз**, хранится только его хэш.
API действует от имени владельца ключа и с его правами в админке (добавление компонентов, для `upsert` —
изменение). Обычный сотрудник выпускает ключи только на себя. Ключ можно отключить или задать срок.
Все действия через API попадают в журнал админки с названием ключа.

```
Authorization: Bearer alk_…          (или X-API-Key: alk_…)
```

| метод | адрес | |
|---|---|---|
| `GET` | `/api/v1/references/` | классы (с путями), производители, магазины, символы, посадочные места |
| `GET` | `/api/v1/components/?manufacturer=&mpn=&mpn_contains=&design_item_id=&limit=&offset=` | поиск |
| `POST` | `/api/v1/components/bulk/` | массовое добавление / обновление |

```json
{
  "mode": "create",
  "dry_run": true,
  "defaults": {
    "manufacturer": "Vishay", "class": "Passive / Resistor", "symbol": "STD_RES",
    "footprints": ["RESC1608X50AN"], "voltage": "75V", "tolerance": "1%", "tolerance_pct": 1
  },
  "components": [
    {"manufacturer_pn": "CRCW060310K0FKEA", "value": "10k", "value_si": 10000,
     "suppliers": [{"supplier": "LCSC", "pn": "C…"}]},
    {"manufacturer_pn": "CRCW060322K0FKEA", "value": "22k", "value_si": 22000}
  ]
}
```

- **`defaults`** — общие поля для всех компонентов запроса; поле в компоненте их перекрывает.
- **Поля компонента:** `manufacturer`, `manufacturer_pn`, `class` (имя или путь «A / B»), `symbol`,
  `footprints` (до 4, первое — основное), `suppliers` (до 3), `comment`, `description`, `value`, `voltage`,
  `tolerance`, `value_si`, `voltage_v`, `tolerance_pct`, `datasheet_url`, `status`.
  Символ и посадочное место — по имени, `{"ref": …, "path": …}` (если имя есть в нескольких файлах) или `{"id": …}`.
- **`mode`:** `create` — уже заведённый MPN (производитель + MPN) считается ошибкой; `upsert` — обновляет его:
  меняются только переданные поля, `footprints` / `suppliers` заменяются, только если переданы.
- **`dry_run: true`** — проверить, ничего не записывая.
- **Всё или ничего:** при любой ошибке ничего не записывается; ответ `400` с ошибками по каждому компоненту
  (`results[i].errors`). Успех — `201` (что-то создано) или `200`, в `results[i].design_item_id` — выданные ID.
- Лимиты: до 2000 компонентов и 10 МБ на запрос (`LIBRARY_API_MAX_ITEMS`, `LIBRARY_API_MAX_BODY_BYTES`);
  2000 компонентов обрабатываются примерно за 7 с.

```powershell
$env:ALTIUM_LIBRARY_API_KEY = "alk_…"
python examples/api_resistor_series.py --series E24 --decades 1 2 3 4 5            # проверка
python examples/api_resistor_series.py --series E24 --decades 1 2 3 4 5 --apply    # запись
```

## Тесты

Тестовая база создаётся из тех же миграций, поэтому нужен пользователь БД с правом CREATEDB:

```sh
docker compose build web
docker compose run --rm --entrypoint python -e DB_USER=postgres -e DB_PASSWORD=<POSTGRES_PASSWORD> web manage.py test library
```

## Разработка сайта без Docker-образа

База — в Docker, сайт — из `.venv` с автоперезагрузкой при правке кода:

```powershell
docker compose up -d db
python -m venv .venv; .venv\Scripts\pip install -r web\requirements.txt   # один раз
web\run.ps1                   # migrate под library_owner, runserver под library_web
```

Сайт откроется на http://127.0.0.1:8001 (8000 занят Docker-контейнером `web`; другой порт — `-Port 8002`,
без миграций — `-SkipMigrate`). Пароли и ключ `run.ps1` берёт из `.env`.
