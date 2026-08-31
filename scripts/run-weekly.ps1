# Ejecuta el pipeline semanal de Futbol Predict (Fase 5) y guarda un log.
#
# Pensado para Windows Task Scheduler. Usa el interprete del entorno virtual
# creado por `uv sync` y corre desde backend/ para que la CLI lea backend/.env
# (DATABASE_URL) y la cache relativa data/raw/.
#
# Uso manual:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-weekly.ps1

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "No se encontro el interprete: $python. Corre 'uv sync' en backend primero."
    exit 1
}

$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logDir "run-weekly-$stamp.log"

Set-Location $backend
Write-Output "== Futbol Predict run-weekly $stamp ==" | Tee-Object -FilePath $log
& $python -m futpredict.cli run-weekly *>> $log
$code = $LASTEXITCODE
Write-Output "== exit=$code ==" | Tee-Object -FilePath $log -Append
exit $code
