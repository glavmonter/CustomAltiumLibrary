"""SQL-файлы миграций схемы: library/migrations/sql/<имя>.sql."""

from pathlib import Path

from django.db import migrations

SQL_DIR = Path(__file__).resolve().parent / "migrations" / "sql"


def read_sql(name):
    return (SQL_DIR / name).read_text(encoding="utf-8")


def run_sql_file(name, reverse_sql=None):
    """RunSQL из файла. reverse_sql — SQL отката или имя .sql-файла; None — миграция необратима."""
    if reverse_sql and reverse_sql.endswith(".sql"):
        reverse_sql = read_sql(reverse_sql)
    return migrations.RunSQL(read_sql(name), reverse_sql=reverse_sql)
