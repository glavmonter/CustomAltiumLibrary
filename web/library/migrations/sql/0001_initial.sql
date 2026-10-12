-- =====================================================================
--  Библиотека компонентов Altium Designer на PostgreSQL — начальная схема.
--  Одна БД, сквозной Design Item ID для всех классов компонентов.
--
--  Выполняется миграцией library/0001_initial (manage.py migrate) от имени
--  владельца схем. Файл не редактировать: изменения — новыми миграциями.
--
--  Схемы:
--    lib     — нормализованные данные (пишет сайт / скрипты импорта)
--    altium  — представления только для чтения, которые видит Altium (DbLib через ODBC)
--    public  — служебные таблицы Django
--
--  PostgreSQL 13+
-- =====================================================================

-- Роли кластерные, их создаёт администратор БД (в Docker — docker/db/10_roles.sh)
DO $$
DECLARE
    missing text;
BEGIN
    SELECT string_agg(r, ', ') INTO missing
    FROM unnest(ARRAY['library_web', 'altium_reader']) AS r
    WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'Не найдены роли: %. Создайте их до миграции (CREATE ROLE ... LOGIN PASSWORD ...)', missing;
    END IF;
END $$;

CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- нечёткий поиск по MPN/описанию на сайте

CREATE SCHEMA IF NOT EXISTS lib;
CREATE SCHEMA IF NOT EXISTS altium;

-- ---------------------------------------------------------------------
--  Общее: автообновление updated_at
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION lib.touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$;

-- ---------------------------------------------------------------------
--  Медиа: картинки УГО и посадочных мест для сайта.
--  Хранятся в БД (bytea) — один pg_dump = полный бэкап библиотеки.
--  Дубликаты отсекаются по sha256.
-- ---------------------------------------------------------------------
CREATE TABLE lib.media (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sha256      bytea       NOT NULL UNIQUE CHECK (length(sha256) = 32),
    mime_type   text        NOT NULL CHECK (mime_type IN ('image/png','image/svg+xml','image/jpeg','image/webp')),
    data        bytea       NOT NULL,
    width_px    integer,
    height_px   integer,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
--  Справочники
-- ---------------------------------------------------------------------
CREATE TABLE lib.manufacturers (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        text NOT NULL,
    website     text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT manufacturers_name_uq UNIQUE (name)
);

CREATE TABLE lib.suppliers (               -- магазины: ChipDip, Элитан, LCSC, Mouser...
    id                   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                 text NOT NULL UNIQUE,
    website              text,
    -- шаблон ссылки на товар, {pn} заменяется на артикул магазина
    -- напр. 'https://www.lcsc.com/product-detail/{pn}.html'
    product_url_template text
);

-- Классы компонентов (иерархия: Passive → Resistor → Chip Resistor)
CREATE TABLE lib.component_classes (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parent_id   integer REFERENCES lib.component_classes(id) ON DELETE RESTRICT,
    name        text NOT NULL,                       -- то, что видно в Altium как "Class"
    -- имя представления altium.<view_name>; NULL = класс не выводится отдельной вкладкой
    view_name   text UNIQUE CHECK (view_name ~ '^[a-z][a-z0-9_]{0,50}$'),
    designator_prefix text,                          -- R, C, U, D, ...
    sort_order  integer NOT NULL DEFAULT 0,
    CONSTRAINT component_classes_name_uq UNIQUE (parent_id, name)
);

-- ---------------------------------------------------------------------
--  Символы (УГО) и посадочные места — ссылки на SchLib/PcbLib
-- ---------------------------------------------------------------------
CREATE TABLE lib.symbols (
    id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    library_ref      text NOT NULL,                  -- имя символа в SchLib
    library_path     text NOT NULL,                  -- путь к .SchLib относительно .DbLib
    preview_media_id bigint REFERENCES lib.media(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT symbols_uq UNIQUE (library_path, library_ref)
);

CREATE TABLE lib.footprints (
    id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    footprint_ref    text NOT NULL,                  -- имя посадочного места в PcbLib
    footprint_path   text NOT NULL,                  -- путь к .PcbLib относительно .DbLib
    description      text,                           -- "SOIC-8, 3.9x4.9 mm, pitch 1.27"
    preview_media_id bigint REFERENCES lib.media(id) ON DELETE SET NULL,   -- 2D-вид
    preview3d_media_id bigint REFERENCES lib.media(id) ON DELETE SET NULL, -- 3D-рендер (опционально)
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT footprints_uq UNIQUE (footprint_path, footprint_ref)
);

CREATE TRIGGER symbols_touch    BEFORE UPDATE ON lib.symbols    FOR EACH ROW EXECUTE FUNCTION lib.touch_updated_at();
CREATE TRIGGER footprints_touch BEFORE UPDATE ON lib.footprints FOR EACH ROW EXECUTE FUNCTION lib.touch_updated_at();

-- ---------------------------------------------------------------------
--  Компоненты — главная таблица.
--  Design Item ID сквозной: генерируется из глобального identity,
--  не зависит от класса и никогда не переиспользуется.
-- ---------------------------------------------------------------------
CREATE TYPE lib.lifecycle_status AS ENUM ('active', 'nrnd', 'obsolete', 'draft');

CREATE TABLE lib.components (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- greatest(): lpad обрезает длинные строки, без этого id 1234567 дал бы 'CMP-123456'
    design_item_id   text GENERATED ALWAYS AS
                     ('CMP-' || lpad(id::text, greatest(6, length(id::text)), '0')) STORED UNIQUE,

    class_id         integer NOT NULL REFERENCES lib.component_classes(id) ON DELETE RESTRICT,
    manufacturer_id  integer NOT NULL REFERENCES lib.manufacturers(id)     ON DELETE RESTRICT,
    manufacturer_pn  text    NOT NULL,                -- MPN, "имя у производителя"

    symbol_id        integer NOT NULL REFERENCES lib.symbols(id)    ON DELETE RESTRICT,
    -- посадочные места — в lib.component_footprints (основное + до трёх альтернативных)

    comment          text,                            -- поле Comment в Altium (обычно = Value или MPN)
    description      text,

    -- параметры в том виде, как их видит инженер и Altium
    value            text,                            -- '10k', '100nF', 'STM32F103C8'
    voltage          text,                            -- '50V'
    tolerance        text,                            -- '1%'
    -- нормализованные числа для фильтров на сайте (заполняются импортом, опционально)
    value_si         numeric,                         -- 10000 (Ом), 1e-7 (Ф)
    voltage_v        numeric,
    tolerance_pct    numeric,

    datasheet_url    text CHECK (datasheet_url IS NULL OR datasheet_url ~* '^https?://'),  -- -> HelpURL
    status           lib.lifecycle_status NOT NULL DEFAULT 'active',

    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT components_mpn_uq UNIQUE (manufacturer_id, manufacturer_pn)
);

CREATE INDEX components_class_idx     ON lib.components (class_id);
CREATE INDEX components_symbol_idx    ON lib.components (symbol_id);
CREATE INDEX components_mpn_trgm      ON lib.components USING gin (manufacturer_pn gin_trgm_ops);
CREATE INDEX components_descr_trgm    ON lib.components USING gin (description gin_trgm_ops);

CREATE TRIGGER components_touch BEFORE UPDATE ON lib.components FOR EACH ROW EXECUTE FUNCTION lib.touch_updated_at();

-- ---------------------------------------------------------------------
--  Посадочные места компонента: slot 1 — основное, 2..4 — альтернативные.
--  Нет строк — компонент без PCB (напр. программный).
--  В Altium: Footprint Ref / Footprint Ref 2..4 (+ Footprint Path N).
-- ---------------------------------------------------------------------
CREATE TABLE lib.component_footprints (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- суррогатный ключ для Django ORM
    component_id  bigint   NOT NULL REFERENCES lib.components(id) ON DELETE CASCADE,
    slot          smallint NOT NULL CHECK (slot BETWEEN 1 AND 4),
    footprint_id  integer  NOT NULL REFERENCES lib.footprints(id) ON DELETE RESTRICT,
    -- проверка при COMMIT: можно менять слоты местами (в т.ч. из Django admin)
    CONSTRAINT component_footprints_slot_uq UNIQUE (component_id, slot) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT component_footprints_uq UNIQUE (component_id, footprint_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX component_footprints_fp_idx ON lib.component_footprints (footprint_id);

-- ---------------------------------------------------------------------
--  Магазины компонента: не более трёх (slot 1..3)
-- ---------------------------------------------------------------------
CREATE TABLE lib.component_suppliers (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- суррогатный ключ для Django ORM
    component_id  bigint   NOT NULL REFERENCES lib.components(id) ON DELETE CASCADE,
    slot          smallint NOT NULL CHECK (slot BETWEEN 1 AND 3),
    supplier_id   integer  NOT NULL REFERENCES lib.suppliers(id) ON DELETE RESTRICT,
    supplier_pn   text     NOT NULL,                  -- артикул в магазине
    product_url   text,                               -- явная ссылка; если NULL — строится из шаблона
    -- проверка при COMMIT: можно менять слоты местами (в т.ч. из Django admin)
    CONSTRAINT component_suppliers_slot_uq UNIQUE (component_id, slot) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT component_suppliers_uq UNIQUE (component_id, supplier_id) DEFERRABLE INITIALLY DEFERRED
);

-- =====================================================================
--  Представления
-- =====================================================================

-- Полное имя класса "Passive / Resistor / Chip Resistor"
CREATE OR REPLACE VIEW lib.v_class_paths AS
WITH RECURSIVE t AS (
    SELECT id, parent_id, name, name AS full_path, id AS root_id
    FROM lib.component_classes WHERE parent_id IS NULL
    UNION ALL
    SELECT c.id, c.parent_id, c.name, t.full_path || ' / ' || c.name, t.root_id
    FROM lib.component_classes c JOIN t ON c.parent_id = t.id
)
SELECT * FROM t;

-- Магазины с готовой ссылкой
CREATE OR REPLACE VIEW lib.v_component_suppliers AS
SELECT cs.component_id, cs.slot, s.name AS supplier, cs.supplier_pn,
       COALESCE(cs.product_url, replace(s.product_url_template, '{pn}', cs.supplier_pn)) AS url
FROM lib.component_suppliers cs
JOIN lib.suppliers s ON s.id = cs.supplier_id;

-- Посадочные места компонента по слотам
CREATE OR REPLACE VIEW lib.v_component_footprints AS
SELECT cf.component_id, cf.slot, f.id AS footprint_id,
       f.footprint_ref, f.footprint_path, f.description,
       f.preview_media_id, f.preview3d_media_id
FROM lib.component_footprints cf
JOIN lib.footprints f ON f.id = cf.footprint_id;

-- ---------------------------------------------------------------------
--  Всё, что видит Altium. Имена колонок — как ожидает Altium:
--  Library Ref / Library Path / Footprint Ref [N] / Footprint Path [N] / HelpURL /
--  Manufacturer 1 / Manufacturer Part Number 1 / Supplier N / Supplier Part Number N
--  ComponentLinkN — кликабельные ссылки в панели Properties.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW altium.all_components AS
SELECT
    c.design_item_id                       AS "Design Item ID",
    s.library_ref                          AS "Library Ref",
    s.library_path                         AS "Library Path",
    fp1.footprint_ref AS "Footprint Ref",   fp1.footprint_path AS "Footprint Path",
    fp2.footprint_ref AS "Footprint Ref 2", fp2.footprint_path AS "Footprint Path 2",
    fp3.footprint_ref AS "Footprint Ref 3", fp3.footprint_path AS "Footprint Path 3",
    fp4.footprint_ref AS "Footprint Ref 4", fp4.footprint_path AS "Footprint Path 4",
    COALESCE(c.comment, c.value, c.manufacturer_pn) AS "Comment",
    c.description                          AS "Description",
    cp.name                                AS "Class",
    c.value                                AS "Value",
    c.voltage                              AS "Voltage",
    c.tolerance                            AS "Tolerance",
    m.name                                 AS "Manufacturer 1",
    c.manufacturer_pn                      AS "Manufacturer Part Number 1",
    sp1.supplier AS "Supplier 1", sp1.supplier_pn AS "Supplier Part Number 1",
    sp2.supplier AS "Supplier 2", sp2.supplier_pn AS "Supplier Part Number 2",
    sp3.supplier AS "Supplier 3", sp3.supplier_pn AS "Supplier Part Number 3",
    c.datasheet_url                        AS "HelpURL",
    CASE WHEN c.datasheet_url IS NOT NULL THEN 'Datasheet' END AS "ComponentLink1Description",
    c.datasheet_url                        AS "ComponentLink1URL",
    sp1.supplier AS "ComponentLink2Description", sp1.url AS "ComponentLink2URL",
    sp2.supplier AS "ComponentLink3Description", sp2.url AS "ComponentLink3URL",
    sp3.supplier AS "ComponentLink4Description", sp3.url AS "ComponentLink4URL",
    c.status::text                         AS "Lifecycle"
FROM lib.components c
JOIN lib.component_classes cp ON cp.id = c.class_id
JOIN lib.manufacturers     m  ON m.id  = c.manufacturer_id
JOIN lib.symbols           s  ON s.id  = c.symbol_id
LEFT JOIN lib.v_component_footprints fp1 ON fp1.component_id = c.id AND fp1.slot = 1
LEFT JOIN lib.v_component_footprints fp2 ON fp2.component_id = c.id AND fp2.slot = 2
LEFT JOIN lib.v_component_footprints fp3 ON fp3.component_id = c.id AND fp3.slot = 3
LEFT JOIN lib.v_component_footprints fp4 ON fp4.component_id = c.id AND fp4.slot = 4
LEFT JOIN lib.v_component_suppliers sp1 ON sp1.component_id = c.id AND sp1.slot = 1
LEFT JOIN lib.v_component_suppliers sp2 ON sp2.component_id = c.id AND sp2.slot = 2
LEFT JOIN lib.v_component_suppliers sp3 ON sp3.component_id = c.id AND sp3.slot = 3
WHERE c.status <> 'draft';

-- ---------------------------------------------------------------------
--  Представления по классам — по одной вкладке в Altium на класс.
--  Класс с view_name включает все дочерние классы.
--  Пересоздаются автоматически триггером при изменении lib.component_classes;
--  вручную: SELECT altium.refresh_class_views();
--  SECURITY DEFINER — чтобы сайт мог менять классы без прав DDL на схему altium.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION altium.refresh_class_views() RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    r record;
    n integer := 0;
BEGIN
    -- удалить старые per-class представления (всё в схеме altium, кроме all_components)
    FOR r IN SELECT table_name FROM information_schema.views
             WHERE table_schema = 'altium' AND table_name <> 'all_components'
    LOOP
        EXECUTE format('DROP VIEW altium.%I', r.table_name);
    END LOOP;

    FOR r IN SELECT id, view_name FROM lib.component_classes WHERE view_name IS NOT NULL
    LOOP
        EXECUTE format($v$
            CREATE VIEW altium.%I AS
            WITH RECURSIVE sub AS (
                SELECT id FROM lib.component_classes WHERE id = %s
                UNION ALL
                SELECT c.id FROM lib.component_classes c JOIN sub ON c.parent_id = sub.id
            )
            SELECT a.* FROM altium.all_components a
            JOIN lib.components c ON c.design_item_id = a."Design Item ID"
            WHERE c.class_id IN (SELECT id FROM sub)
        $v$, r.view_name, r.id);
        EXECUTE format('GRANT SELECT ON altium.%I TO altium_reader, library_web', r.view_name);
        n := n + 1;
    END LOOP;
    RETURN n;
END $$;

REVOKE ALL ON FUNCTION altium.refresh_class_views() FROM PUBLIC;

CREATE OR REPLACE FUNCTION lib.component_classes_changed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM altium.refresh_class_views();
    RETURN NULL;
END $$;

CREATE TRIGGER component_classes_refresh_views
    AFTER INSERT OR DELETE OR UPDATE OF parent_id, view_name ON lib.component_classes
    FOR EACH STATEMENT EXECUTE FUNCTION lib.component_classes_changed();

-- ---------------------------------------------------------------------
--  Карточка компонента для сайта: всё из Altium + УГО + посадочные места
--  (footprint_* — основное, footprints — все слоты с картинками)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW lib.v_component_card AS
SELECT
    c.id, c.design_item_id,
    cp.full_path          AS class_path,
    m.name                AS manufacturer, m.website AS manufacturer_site,
    c.manufacturer_pn, c.description, c.comment,
    c.value, c.voltage, c.tolerance,
    c.value_si, c.voltage_v, c.tolerance_pct,
    c.datasheet_url, c.status,
    s.library_ref, s.library_path, s.preview_media_id  AS symbol_image_id,
    f.footprint_ref, f.footprint_path, f.description   AS footprint_description,
    f.preview_media_id   AS footprint_image_id,   -- основное посадочное место
    f.preview3d_media_id AS footprint_3d_image_id,
    COALESCE((SELECT jsonb_agg(jsonb_build_object('slot', v.slot, 'supplier', v.supplier,
                                                  'pn', v.supplier_pn, 'url', v.url) ORDER BY v.slot)
              FROM lib.v_component_suppliers v WHERE v.component_id = c.id), '[]'::jsonb) AS suppliers,
    COALESCE((SELECT jsonb_agg(jsonb_build_object('slot', v.slot, 'primary', v.slot = 1,
                                                  'ref', v.footprint_ref, 'path', v.footprint_path,
                                                  'description', v.description,
                                                  'image_id', v.preview_media_id,
                                                  'image3d_id', v.preview3d_media_id) ORDER BY v.slot)
              FROM lib.v_component_footprints v WHERE v.component_id = c.id), '[]'::jsonb) AS footprints,
    c.created_at, c.updated_at
FROM lib.components c
JOIN lib.v_class_paths cp ON cp.id = c.class_id
JOIN lib.manufacturers m  ON m.id  = c.manufacturer_id
JOIN lib.symbols s        ON s.id  = c.symbol_id
LEFT JOIN lib.v_component_footprints f ON f.component_id = c.id AND f.slot = 1;

-- =====================================================================
--  Права
-- =====================================================================

-- Altium: только чтение представлений altium.*
GRANT USAGE ON SCHEMA altium TO altium_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA altium TO altium_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA altium GRANT SELECT ON TABLES TO altium_reader;
-- представления выполняются с правами владельца, прямой доступ к lib.* не нужен

-- Сайт: чтение/запись данных библиотеки
GRANT USAGE ON SCHEMA lib, altium TO library_web;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA lib TO library_web;
GRANT SELECT ON ALL TABLES IN SCHEMA altium TO library_web;
GRANT EXECUTE ON FUNCTION altium.refresh_class_views() TO library_web;  -- вызывается триггером на component_classes
GRANT USAGE ON ALL SEQUENCES IN SCHEMA lib TO library_web;
ALTER DEFAULT PRIVILEGES IN SCHEMA lib GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO library_web;
ALTER DEFAULT PRIVILEGES IN SCHEMA lib GRANT USAGE ON SEQUENCES TO library_web;

-- Служебные таблицы Django (auth, sessions, admin) в public создаются миграциями
-- после этой (run_before в 0001_initial.py), поэтому сайту хватает прав по умолчанию
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO library_web;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO library_web;
