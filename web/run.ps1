# Запуск сайта без Docker-образа (база — в Docker: docker compose up -d db).
# Пароли и ключ берутся из ..\.env, в этом файле их нет.
#
#   .\run.ps1                # миграции + сервер разработки на http://127.0.0.1:8000
#   .\run.ps1 -Port 8001
#   .\run.ps1 -SkipMigrate
#
# Порт по умолчанию 8000
param(
    [int]$Port = 8000,
    [switch]$SkipMigrate
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$envFile = Join-Path $PSScriptRoot '..\.env'
if (-not (Test-Path $envFile)) { throw "Не найден $envFile — скопируйте .env.example в .env" }
$cfg = @{}
foreach ($line in Get-Content $envFile -Encoding UTF8) {
    if ($line -match '^\s*([^#=\s][^=]*?)\s*=\s*(.*)$') { $cfg[$Matches[1]] = $Matches[2] }
}

$python = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
$env:DJANGO_SECRET_KEY = $cfg['DJANGO_SECRET_KEY']
$env:DJANGO_DEBUG = '1'
$env:DB_HOST = 'localhost'
$env:DB_PORT = if ($cfg['PG_PORT']) { $cfg['PG_PORT'] } else { '5432' }
$env:DB_NAME = if ($cfg['POSTGRES_DB']) { $cfg['POSTGRES_DB'] } else { 'altium_library' }

if (-not $SkipMigrate) {
    # миграции меняют схему — под владельцем схем
    $env:DB_USER = 'library_owner'; $env:DB_PASSWORD = $cfg['LIBRARY_OWNER_PASSWORD']
    & $python manage.py migrate
    if ($LASTEXITCODE -ne 0) { throw 'migrate завершился с ошибкой' }
}

$env:DB_USER = 'library_web'; $env:DB_PASSWORD = $cfg['LIBRARY_WEB_PASSWORD']
& $python manage.py runserver "127.0.0.1:$Port"
