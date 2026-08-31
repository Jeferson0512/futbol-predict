# Handoff para continuar en otra PC

Este documento resume como dejar el proyecto operativo despues de clonarlo en
otra computadora y que partes ya quedaron listas.

## Arranque recomendado

```powershell
git clone https://github.com/Jeferson0512/futbol-predict.git
cd futbol-predict
copy .env.example .env
docker compose up -d --build postgres api frontend mlflow
```

Servicios locales:

```text
Frontend: http://localhost:5173
API:      http://localhost:8000
OpenAPI:  http://localhost:8000/docs
MLflow:   http://localhost:5000
Postgres: localhost:5433
```

## Restaurar DB incluida

El backup versionado esta en:

```text
backups/postgres/futbol_predict_2026-08-27.dump
```

Para restaurarlo:

```powershell
docker compose up -d postgres
docker cp backups\postgres\futbol_predict_2026-08-27.dump futbol_predict_postgres:/tmp/futbol_predict_2026-08-27.dump
docker compose exec postgres pg_restore -U futbol -d futbol_predict --clean --if-exists --no-owner --no-privileges /tmp/futbol_predict_2026-08-27.dump
```

Luego verificar:

```powershell
docker compose exec api python -m futpredict.cli db-status
docker compose exec api python -m futpredict.cli model-metrics-status
docker compose exec api python -m futpredict.cli predictions-status
docker compose exec api python -m futpredict.cli calibration-status --bins 10
```

Si MLflow no tiene runs todavia:

```powershell
docker compose exec api python -m futpredict.cli sync-mlflow-model-versions --force
```

## Hecho hasta ahora

- Monorepo backend/frontend creado.
- Docker Compose con PostgreSQL, API, frontend, worker y MLflow.
- FastAPI con healthcheck, endpoints de metricas, calibracion, rankings,
  fixture predictions y OpenAPI.
- PostgreSQL con migraciones Alembic.
- Ingesta historica Big-5 desde `football-data.co.uk`.
- Normalizacion de ligas, temporadas, equipos, aliases, partidos y cuotas.
- Features historicas con fecha de corte.
- Elo propio persistido por partido.
- Backtests desde PostgreSQL.
- Walk-forward temporal con 35 ventanas historicas.
- Baselines: `always_home`, `historical_frequency`, `elo_simple`,
  `market_avg_odds` y `club_elo`.
- Club Elo con cache local completa validada: 161/161 equipos y cobertura
  17,937/17,937 partidos.
- Registro inmutable de predicciones historicas.
- Evaluacion post-partido con RPS, log-loss y Brier.
- Curvas de calibracion con 10 bins.
- MLflow integrado por REST y enlazado desde `model_versions.artifact_uri`.
- Dashboard React/Vite consumiendo la API local.
- Tipos TypeScript generados desde OpenAPI.
- CI basico en GitHub Actions.

## Estado de datos incluido en el backup

```text
leagues:          5
teams:            161
matches:          17941
odds:             17941
features:         17937
elo_ratings:      35874
model_versions:   175
model_metrics:    175
predictions:      62295
calibration_bins: 2048
```

Metricas walk-forward actuales:

```text
model,windows,matches,weighted_rps,weighted_log_loss,weighted_brier,weighted_accuracy
market_avg_odds,35,12459,0.195621,0.970525,0.576858,0.5395
elo_simple,35,12459,0.202574,0.996063,0.593951,0.5229
club_elo,35,12459,0.202676,0.995811,0.594156,0.5249
historical_frequency,35,12459,0.230938,1.074852,0.650668,0.4308
always_home,35,12459,0.442973,19.660406,1.138454,0.4308
```

## Falta para Fase 5

- Job semanal real.
- Reentrenamiento walk-forward automatico.
- Promocion automatica del modelo campeon por RPS.
- Congelar predicciones futuras antes del partido.
- Definir politica de ejecucion: manual local, Windows Task Scheduler, cron en
  contenedor o GitHub Actions.
- Decidir si los fixtures futuros se refrescan solo desde `football-data.co.uk`
  o si se agrega otra fuente/API.

## Notas importantes

- No abrir `frontend/index.html` con `file:///`; usar `http://localhost:5173`.
- `.env` esta ignorado. Crear una copia desde `.env.example` en cada PC.
- `backend/data/raw/` queda versionado en este handoff porque contiene CSVs
  publicos y la cache Club Elo completa. Esto permite continuar en otra PC con
  menos dependencia de descargas externas.
- Nuevas caches grandes deben revisarse antes de subirlas; el backup
  PostgreSQL sigue siendo la fuente principal para restaurar el estado de la DB.
