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
# PowerShell 5.1 convierte CADA linea que el exe escribe en stderr en un
# NativeCommandError cuando se redirige con `*>>`. Con ErrorActionPreference
# en "Stop" eso ABORTA el script a media corrida: el semanal moria en
# ingest_xg en cuanto soccerdata escribia una linea informativa, sin llegar a
# reentrenar, recalibrar ni promover campeon. El estado real de un exe lo da
# $LASTEXITCODE, no $?.
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $python -m futpredict.cli run-weekly *>> $log
$code = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
Write-Output "== exit=$code ==" | Tee-Object -FilePath $log -Append
exit $code
