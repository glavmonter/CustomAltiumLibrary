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

## Разработка сайта без Docker-образа

```powershell
docker compose up -d db
cd web
$env:DJANGO_SECRET_KEY = "dev"; $env:DJANGO_DEBUG = "1"
$env:DB_USER = "library_owner"; $env:DB_PASSWORD = "<LIBRARY_OWNER_PASSWORD из .env>"
..\.venv\Scripts\python manage.py migrate
$env:DB_USER = "library_web"; $env:DB_PASSWORD = "<LIBRARY_WEB_PASSWORD из .env>"
..\.venv\Scripts\python manage.py runserver
```
