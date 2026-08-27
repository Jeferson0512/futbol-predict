# Futbol Predict

Sistema local para prediccion probabilistica 1X2 de partidos de futbol.

La meta de la primera version no es prometer porcentajes irreales. La meta es
crear un pipeline honesto: datos historicos, predicciones congeladas antes del
partido, evaluacion temporal, RPS, calibracion y comparacion contra baselines.

## Estado actual

Esta base deja listas las fases principales de datos, baselines y medicion
historica:

- API FastAPI con `/health`.
- Configuracion tipada por variables de entorno.
- Modelos SQLAlchemy para ligas, equipos, partidos, cuotas, Elo, features,
  versiones de modelo, predicciones y metricas.
- Migracion Alembic inicial para PostgreSQL.
- Tabla normalizada de aliases de equipos por fuente.
- Implementacion propia de Elo.
- Implementacion propia de RPS.
- Adaptador inicial para CSVs gratis de `football-data.co.uk`.
- Carga normalizada y backtests desde PostgreSQL local.
- Registro inmutable de predicciones walk-forward.
- Evaluador post-partido con RPS, log-loss y Brier.
- Curvas de calibracion persistidas por bins.
- Benchmark externo `club_elo` con cache local completa.
- Runs MLflow enlazados desde `model_versions.artifact_uri`.
- Fixtures proximos desde el CSV semanal gratuito de `football-data.co.uk`.
- Predicciones futuras transitorias por mejor modelo disponible.
- Tipos TypeScript generados desde OpenAPI.
- CI basico en GitHub Actions.
- Tests unitarios para RPS, Elo y guardas anti-leakage.
- Frontend Vite/React con dashboard de metricas historicas.
- Docker Compose con PostgreSQL, API, worker, MLflow y frontend.

## Requisitos

- Python 3.12 o 3.13.
- `uv`.
- Docker Desktop.
- Node.js 20+ para el frontend.

## Primer arranque local

```powershell
cd D:\Trabajos\Propios\futbol-predict
copy .env.example .env
docker compose up -d --build postgres api frontend mlflow
```

Luego:

- API: `http://localhost:8000/health`
- Docs OpenAPI: `http://localhost:8000/docs`
- Frontend: `http://localhost:5173`
- MLflow: `http://localhost:5000`
- PostgreSQL del proyecto: `localhost:5433` desde Windows, `postgres:5432` dentro de Docker Compose.

No abras `frontend/index.html` directamente con `file:///`; Vite/React debe servirse por HTTP.
Para verificar el estado del stack:

```powershell
docker compose ps
docker compose logs --tail=80 api frontend
```

Comandos utiles usando Docker:

```powershell
cd D:\Trabajos\Propios\futbol-predict
docker compose run --rm api alembic upgrade head
docker compose exec api python -m futpredict.cli db-status
docker compose exec api python -m futpredict.cli team-aliases-status
docker compose exec api python -m futpredict.cli features-status
docker compose exec api python -m futpredict.cli elo-ratings-status
docker compose exec api python -m futpredict.cli model-metrics-status
docker compose exec api python -m futpredict.cli predictions-status
docker compose exec api python -m futpredict.cli calibration-status --bins 10
docker compose exec api python -m futpredict.cli sync-mlflow-model-versions
docker compose exec api python -m futpredict.cli load-big-five-fixtures-db --season 2627 --force
docker compose exec api python -m futpredict.cli fixtures-status
```

## Backend sin Docker

```powershell
cd D:\Trabajos\Propios\futbol-predict\backend
uv sync --extra dev
uv run pytest
uv run uvicorn futpredict.main:app --reload
```

Para usar PostgreSQL desde el backend local, define `DATABASE_URL` con el host
accesible desde Windows. Si PostgreSQL viene de Docker Compose, normalmente el
host local sera `localhost`; dentro de Docker Compose el host sera `postgres`.

```powershell
cd D:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli db-status
```

## Ingesta inicial gratuita

La fuente recomendada para empezar es `football-data.co.uk`, porque publica
CSVs gratis con resultados historicos, estadisticas y cuotas.

Ejemplo:

```powershell
cd D:\Trabajos\Propios\futbol-predict\backend
uv run futpredict ingest-football-data-uk --season 2526 --division E0
```

`2526` representa la temporada 2025/26 y `E0` la Premier League.

Tambien puedes guardar el CSV en cache y correr el primer backtest local:

```powershell
cd D:\Trabajos\Propios\futbol-predict\backend
.\.venv\Scripts\python.exe -m futpredict.cli download-football-data-uk --season 2526 --division E0
.\.venv\Scripts\python.exe -m futpredict.cli backtest-football-data-uk --season 2526 --division E0
```

La salida compara `always_home`, `historical_frequency`, `elo_simple` y
`market_avg_odds` cuando el CSV trae cuotas 1X2. El lector prioriza cuotas
promedio de cierre, luego promedio pre-partido, promedio historico `BbAv*`,
Pinnacle y Bet365 como fallback. Se reporta RPS, log-loss, Brier y accuracy.

Para descargar y evaluar Big-5 en diez temporadas:

```powershell
cd D:\Trabajos\Propios\futbol-predict\backend
.\.venv\Scripts\python.exe -m futpredict.cli download-big-five --start-season 1617 --end-season 2526
.\.venv\Scripts\python.exe -m futpredict.cli backtest-big-five --start-season 1617 --end-season 2526
```

La API expone el agregado y sus desgloses por liga y temporada:

```text
GET /backtests/football-data-uk/big-five?start_season=1617&end_season=2526
```

Para preparar y cargar esos datos a PostgreSQL:

```powershell
cd D:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli load-big-five-db --start-season 1617 --end-season 2526 --dry-run
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m futpredict.cli load-big-five-db --start-season 1617 --end-season 2526
.\.venv\Scripts\python.exe -m futpredict.cli team-aliases-status
```

Para evaluar desde PostgreSQL, sin volver a leer los CSV:

```powershell
cd D:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli backtest-db-football-data-uk --season 2526 --division E0
.\.venv\Scripts\python.exe -m futpredict.cli backtest-db-big-five --start-season 1617 --end-season 2526
```

Para generar features historicos con fecha de corte:

```powershell
cd D:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli build-rolling-features-db --start-season 1617 --end-season 2526 --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli build-rolling-features-db --start-season 1617 --end-season 2526
.\.venv\Scripts\python.exe -m futpredict.cli features-status
```

Para persistir Elo propio por partido:

```powershell
cd D:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli build-elo-ratings-db --start-season 1617 --end-season 2526 --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli build-elo-ratings-db --start-season 1617 --end-season 2526
.\.venv\Scripts\python.exe -m futpredict.cli elo-ratings-status
```

Para ejecutar walk-forward formal y guardar metricas por ventana:

```powershell
cd D:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli walk-forward-db --start-season 1617 --end-season 2526 --initial-train-seasons 3 --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli walk-forward-db --start-season 1617 --end-season 2526 --initial-train-seasons 3
.\.venv\Scripts\python.exe -m futpredict.cli club-elo-coverage-db --start-season 1617 --end-season 2526 --offline
.\.venv\Scripts\python.exe -m futpredict.cli walk-forward-db --start-season 1617 --end-season 2526 --initial-train-seasons 3 --include-club-elo --club-elo-offline
.\.venv\Scripts\python.exe -m futpredict.cli model-metrics-status
```

La API tambien expone backtests basados en BD:

```text
GET /backtests/db/football-data-uk?season=2526&division=E0
GET /backtests/db/big-five?start_season=1617&end_season=2526
GET /predictions/status
GET /calibration/status?bins=10
GET /calibration/curves?bins=10&model=market_avg_odds
GET /models/champion
GET /fixtures/upcoming?days=21&limit=40
GET /fixtures/predictions?days=21&limit=40&model=best_available
```

Para congelar predicciones historicas walk-forward, evaluarlas y construir
calibracion:

```powershell
cd D:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli freeze-walk-forward-predictions-db --start-season 1617 --end-season 2526 --initial-train-seasons 3
.\.venv\Scripts\python.exe -m futpredict.cli freeze-walk-forward-predictions-db --start-season 1617 --end-season 2526 --initial-train-seasons 3 --include-club-elo --club-elo-offline
.\.venv\Scripts\python.exe -m futpredict.cli evaluate-predictions-db
.\.venv\Scripts\python.exe -m futpredict.cli build-calibration-bins-db --bins 10
.\.venv\Scripts\python.exe -m futpredict.cli predictions-status
.\.venv\Scripts\python.exe -m futpredict.cli calibration-status --bins 10
.\.venv\Scripts\python.exe -m futpredict.cli sync-mlflow-model-versions
.\.venv\Scripts\python.exe -m futpredict.cli sync-mlflow-model-versions --force
```

Para cargar fixtures proximos gratuitos y habilitar la vista de predicciones
futuras:

```powershell
cd D:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli download-football-data-uk-fixtures --force
.\.venv\Scripts\python.exe -m futpredict.cli load-big-five-fixtures-db --season 2627 --force
.\.venv\Scripts\python.exe -m futpredict.cli fixtures-status
```

Para regenerar el contrato API del frontend:

```powershell
cd D:\Trabajos\Propios\futbol-predict\backend
.\.venv\Scripts\python.exe -m futpredict.cli export-openapi --output ..\frontend\src\api\openapi.json

cd D:\Trabajos\Propios\futbol-predict\frontend
npm run generate:api-types
```

## Reglas del proyecto

- Nunca usar split aleatorio para validar modelos de partidos.
- Toda feature debe declarar una fecha de corte.
- Ninguna prediccion puede registrarse con `predicted_at >= kickoff_utc`.
- Nunca sobrescribir una prediccion historica.
- El porcentaje de acierto solo sirve para comunicar, no para decidir.
- La metrica principal es RPS.

## Siguiente objetivo

El siguiente paso practico es pasar a Fase 5: congelar predicciones futuras
antes del partido, crear el job semanal y promover el modelo campeon de forma
automatica. Club Elo y MLflow ya quedaron cerrados como pendientes previos.
