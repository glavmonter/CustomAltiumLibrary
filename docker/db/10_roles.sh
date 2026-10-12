#!/bin/sh
# Роли, пароли и владелец базы. Схему создают миграции Django (сервис migrate).
#   library_owner — владелец базы и схем, под ним выполняются миграции
#   library_web   — сайт: чтение/запись данных
#   altium_reader — Altium Designer: только чтение представлений altium.*
#
# Выполняется автоматически при первом запуске на пустом томе. Повторный запуск безопасен
# и синхронизирует пароли с .env (после их смены):
#   docker compose up -d db && docker compose exec db sh /docker-entrypoint-initdb.d/10_roles.sh
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v db="$POSTGRES_DB" \
     -v su="$POSTGRES_USER" \
     -v su_pw="${POSTGRES_PASSWORD:?}" \
     -v owner_pw="${LIBRARY_OWNER_PASSWORD:?}" \
     -v web_pw="${LIBRARY_WEB_PASSWORD:?}" \
     -v altium_pw="${ALTIUM_READER_PASSWORD:?}" <<'EOSQL'
SELECT format('CREATE ROLE %I LOGIN', r)
FROM unnest(ARRAY['library_owner', 'library_web', 'altium_reader']) AS r
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) \gexec

ALTER ROLE :"su"          PASSWORD :'su_pw';
ALTER ROLE library_owner PASSWORD :'owner_pw';
ALTER ROLE library_web   PASSWORD :'web_pw';
ALTER ROLE altium_reader PASSWORD :'altium_pw';
-- владелец базы может создавать схемы и доверенные расширения (pg_trgm); public принадлежит ему же
ALTER DATABASE :"db" OWNER TO library_owner;
EOSQL
