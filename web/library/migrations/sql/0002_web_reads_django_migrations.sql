-- django_migrations создаётся Django до первой миграции, поэтому права по умолчанию из 0001
-- на неё не распространились. Сайту нужно её читать: manage.py runserver / showmigrations
-- при запуске проверяют, все ли миграции применены.
GRANT SELECT ON public.django_migrations TO library_web;
