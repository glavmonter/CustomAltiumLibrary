#!/bin/sh
set -eu

# Миграции выполняет отдельный сервис migrate (под владельцем схем), здесь только запуск сайта
python manage.py ensure_superuser

exec gunicorn altlib.wsgi:application \
     --bind 0.0.0.0:8000 \
     --workers "${GUNICORN_WORKERS:-3}" \
     --access-logfile -
