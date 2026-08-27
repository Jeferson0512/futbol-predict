# Fase 3 - Medicion

Objetivo: congelar predicciones antes de medirlas, y evaluar cada prediccion
post-partido con metricas probabilisticas reproducibles.

## Checklist de trabajo

- [x] Registro inmutable de predicciones.
- [x] Evaluador post-partido.
- [x] RPS, log-loss y Brier por modelo.
- [x] Curvas de calibracion.
- [x] MLflow para versiones y artefactos.

## Comandos de trabajo

Desde Windows:

```powershell
cd D:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli freeze-walk-forward-predictions-db --start-season 1617 --end-season 2526 --initial-train-seasons 3 --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli freeze-walk-forward-predictions-db --start-season 1617 --end-season 2526 --initial-train-seasons 3
.\.venv\Scripts\python.exe -m futpredict.cli evaluate-predictions-db --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli evaluate-predictions-db
.\.venv\Scripts\python.exe -m futpredict.cli predictions-status
.\.venv\Scripts\python.exe -m futpredict.cli build-calibration-bins-db --bins 10 --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli build-calibration-bins-db --bins 10
.\.venv\Scripts\python.exe -m futpredict.cli calibration-status --bins 10
.\.venv\Scripts\python.exe -m futpredict.cli sync-mlflow-model-versions
.\.venv\Scripts\python.exe -m futpredict.cli sync-mlflow-model-versions --force
```

Desde Docker:

```powershell
cd D:\Trabajos\Propios\futbol-predict
docker compose exec api python -m futpredict.cli freeze-walk-forward-predictions-db --start-season 1617 --end-season 2526 --initial-train-seasons 3
docker compose exec api python -m futpredict.cli evaluate-predictions-db
docker compose exec api python -m futpredict.cli predictions-status
docker compose exec api python -m futpredict.cli build-calibration-bins-db --bins 10
docker compose exec api python -m futpredict.cli calibration-status --bins 10
docker compose exec api python -m futpredict.cli sync-mlflow-model-versions
docker compose exec api python -m futpredict.cli sync-mlflow-model-versions --force
```

## Estado actual

Estado validado del 2026-08-27: se congelaron 62,295 predicciones
walk-forward para Big-5 2019/20 a 2025/26, derivadas de 35 ventanas y 175
versiones de modelo. Al incorporar `club_elo`, el congelado inserto 12,459
predicciones nuevas y reutilizo 49,836 existentes.

El evaluador post-partido calculo metricas para las 62,295 predicciones. La
ultima ejecucion proceso 12,459 predicciones pendientes de `club_elo`.

Tambien se construyeron curvas de calibracion con 10 bins para las 175
versiones historicas de modelo. El proceso genero 2,048 bins y 186,885
muestras clase-modelo, usando las probabilidades congeladas ya evaluadas.

```text
model,algorithm,feature_set_version,predictions,evaluated,avg_rps,avg_log_loss,avg_brier
market_avg_odds,market_odds,baseline_walk_forward_v1,12459,12459,0.195621,0.970525,0.576858
elo_simple,elo,baseline_walk_forward_v1,12459,12459,0.202574,0.996063,0.593951
club_elo,external_elo,baseline_walk_forward_v1,12459,12459,0.202676,0.995811,0.594156
historical_frequency,historical_frequency,baseline_walk_forward_v1,12459,12459,0.230938,1.074852,0.650668
always_home,constant_baseline,baseline_walk_forward_v1,12459,12459,0.442973,19.660406,1.138454
```

Estado de calibracion con 10 bins:

```text
model,algorithm,feature_set_version,model_versions,bins,class_samples,calibration_error
historical_frequency,historical_frequency,baseline_walk_forward_v1,35,108,37377,0.022880
elo_simple,elo,baseline_walk_forward_v1,35,555,37377,0.041292
market_avg_odds,market_odds,baseline_walk_forward_v1,35,751,37377,0.043060
club_elo,external_elo,baseline_walk_forward_v1,35,529,37377,0.044280
always_home,constant_baseline,baseline_walk_forward_v1,35,105,37377,0.379485
```

## MLflow

MLflow corre en Docker Compose en `http://localhost:5000`. El backend usa el
tracking URI de `MLFLOW_TRACKING_URI`; dentro del contenedor API apunta a
`http://mlflow:5000`.

El comando `sync-mlflow-model-versions` registra un run por cada fila de
`model_versions` con metricas, parametros, tags de trazabilidad y el
`artifact_uri` devuelto por MLflow. Ese `artifact_uri` se guarda de vuelta en
PostgreSQL.

Estado validado del 2026-08-27:

```text
experiment_id=1
scanned_model_versions=175
created_runs=175
linked_artifacts=175
```

Una segunda ejecucion normal no duplica runs:

```text
skipped_model_versions=175
created_runs=0
```

Despues de recalcular calibracion, `--force` refresco metricas de los runs
existentes sin duplicarlos:

```text
reused_runs=175
created_runs=0
logged_runs=175
```

## Notas tecnicas

La tabla `predictions` mantiene las probabilidades congeladas con la clave unica
`uq_prediction_match_model`. El comando de congelado usa `ON CONFLICT DO
NOTHING`, por lo que repetirlo no modifica predicciones existentes.

El evaluador solo completa campos post-partido: `actual_outcome`, `rps`,
`log_loss` y `brier`. No actualiza probabilidades ya congeladas.

La tabla `calibration_bins` agrega las predicciones evaluadas por version de
modelo, resultado (`H`, `D`, `A`) y rango de probabilidad. El error de
calibracion agregado se calcula ponderando por cantidad de predicciones en cada
bin.

Los upserts de `model_versions` preservan `artifact_uri` cuando un recalculo
walk-forward no trae un nuevo artefacto, para no perder el enlace hacia MLflow.
