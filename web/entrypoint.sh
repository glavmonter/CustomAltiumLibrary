#!/bin/sh
set -eu

# Миграции выполняет отдельный сервис migrate (под владельцем схем), здесь только запуск сайта
python manage.py ensure_superuser

# gthread, а не sync: синхронный воркер, пока читает тело запроса от медленного клиента
# (файл библиотеки до 12 МБ), не отчитывается главному процессу и через --timeout (30 с)
# убивается — соединение рвётся. У gthread запрос обрабатывается в потоке, а воркер
# продолжает отчитываться, поэтому долгая загрузка не считается зависанием.
exec gunicorn altlib.wsgi:application \
     --bind 0.0.0.0:8000 \
     --workers "${GUNICORN_WORKERS:-3}" \
     --worker-class gthread \
     --threads "${GUNICORN_THREADS:-4}" \
     --timeout "${GUNICORN_TIMEOUT:-60}" \
     --access-logfile -
