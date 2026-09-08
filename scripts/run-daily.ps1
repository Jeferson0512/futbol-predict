# Ejecuta el job DIARIO ligero de Futbol Predict (Fase 8) y guarda un log.
#
# A diferencia del semanal, el diario NO re-entrena ni baja los CSV de
# football-data: solo refresca resultados y fixtures desde ESPN (Europa + Peru),
# reconstruye Elo/features, evalua las predicciones ya congeladas contra los
# resultados que fueron saliendo y congela las predicciones de la proxima
# jornada. Se apoya en el campeon que dejo el ultimo run-weekly.
#
# Pensado para Windows Task Scheduler (correr cada dia). Usa el interprete del
# entorno virtual (uv sync) y corre desde backend/ para leer backend/.env.
#
# Uso manual:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-daily.ps1

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
$log = Join-Path $logDir "run-daily-$stamp.log"

Set-Location $backend
Write-Output "== Futbol Predict run-daily $stamp ==" | Tee-Object -FilePath $log
# PowerShell 5.1 convierte CADA linea que el exe escribe en stderr en un
# NativeCommandError cuando se redirige con `*>>`. Con ErrorActionPreference
# en "Stop" eso ABORTA el script a media corrida: el semanal moria en
# ingest_xg en cuanto soccerdata escribia una linea informativa, sin llegar a
# reentrenar, recalibrar ni promover campeon. El estado real de un exe lo da
# $LASTEXITCODE, no $?.
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $python -m futpredict.cli run-daily *>> $log
$code = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
Write-Output "== exit=$code ==" | Tee-Object -FilePath $log -Append
exit $code
