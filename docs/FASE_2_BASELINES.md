# Fase 2 - Baselines

Objetivo: tener baselines reproducibles y auditables antes de entrenar modelos
mas complejos. Un modelo nuevo solo es util si supera estos pisos en evaluacion
temporal.

## Checklist de trabajo

- [x] Baseline siempre local en backtest.
- [x] Baseline por frecuencias historicas de liga en backtest.
- [x] Elo simple en backtest.
- [x] Baseline `market_avg_odds` quitando margen implicito de cuotas.
- [x] Fallback de cuotas para temporadas antiguas.
- [x] Elo propio persistido por partido en PostgreSQL.
- [x] Comparacion contra Club Elo.
  - [x] Adaptador cacheado de historiales Club Elo.
  - [x] Benchmark `club_elo` opcional dentro del walk-forward.
  - [x] Comando de cobertura de aliases/cache.
  - [x] Ejecucion completa con cache local completa.
- [x] Backtest walk-forward formal.
- [x] Persistencia idempotente de metricas walk-forward.

## Comandos de trabajo

Desde Windows:

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli build-elo-ratings-db --start-season 1617 --end-season 2526 --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli build-elo-ratings-db --start-season 1617 --end-season 2526
.\.venv\Scripts\python.exe -m futpredict.cli elo-ratings-status
.\.venv\Scripts\python.exe -m futpredict.cli walk-forward-db --start-season 1617 --end-season 2526 --initial-train-seasons 3 --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli walk-forward-db --start-season 1617 --end-season 2526 --initial-train-seasons 3
.\.venv\Scripts\python.exe -m futpredict.cli model-metrics-status
.\.venv\Scripts\python.exe -m futpredict.cli club-elo-coverage-db --start-season 1617 --end-season 2526 --offline
.\.venv\Scripts\python.exe -m futpredict.cli club-elo-coverage-db --start-season 1617 --end-season 2526 --workers 1 --timeout 60
.\.venv\Scripts\python.exe -m futpredict.cli walk-forward-db --start-season 1617 --end-season 2526 --initial-train-seasons 3 --include-club-elo --club-elo-offline
```

Desde Docker:

```powershell
cd E:\Trabajos\Propios\futbol-predict
docker compose exec api python -m futpredict.cli build-elo-ratings-db --start-season 1617 --end-season 2526 --dry-run
docker compose exec api python -m futpredict.cli build-elo-ratings-db --start-season 1617 --end-season 2526
docker compose exec api python -m futpredict.cli elo-ratings-status
docker compose exec api python -m futpredict.cli walk-forward-db --start-season 1617 --end-season 2526 --initial-train-seasons 3
docker compose exec api python -m futpredict.cli model-metrics-status
docker compose exec api python -m futpredict.cli club-elo-coverage-db --start-season 1617 --end-season 2526 --offline
docker compose exec api python -m futpredict.cli walk-forward-db --start-season 1617 --end-season 2526 --initial-train-seasons 3 --include-club-elo --club-elo-offline
```

## Estado actual

Estado del 2026-08-26: `elo_simple_v1` quedo calculado para Big-5 1617-2526 y
persistido en la tabla `elo_ratings`.

```text
league,ratings,matches
bundesliga,6120,3060
laliga,7600,3800
ligue-1,6954,3477
premier-league,7600,3800
serie-a,7600,3800
```

Total validado: 17,937 partidos y 35,874 ratings.

## Walk-forward

La evaluacion walk-forward usa una ventana expansiva por liga. Con
`--initial-train-seasons 3`, las temporadas 2016/17 a 2018/19 funcionan como
historia inicial y se evaluan las temporadas 2019/20 a 2025/26 una por una.

Cada baseline se guarda en `model_versions` y cada ventana evaluada en
`model_metrics`. Las claves unicas `uq_model_version_identity` y
`uq_model_metric_version_window` permiten repetir el comando sin duplicar filas.

Estado validado del 2026-08-27: Alembic quedo en
`0004_model_metric_idempotency`. El walk-forward `baseline_walk_forward_v1`
quedo persistido con 35 ventanas por modelo y 12,459 partidos evaluados.

```text
model,windows,matches,weighted_rps,weighted_log_loss,weighted_brier,weighted_accuracy
market_avg_odds,35,12459,0.195621,0.970525,0.576858,0.5395
elo_simple,35,12459,0.202574,0.996063,0.593951,0.5229
club_elo,35,12459,0.202676,0.995811,0.594156,0.5249
historical_frequency,35,12459,0.230938,1.074852,0.650668,0.4308
always_home,35,12459,0.442973,19.660406,1.138454,0.4308
```

## Club Elo

Club Elo se integra como benchmark externo gratuito sin token. El adaptador usa
`http://api.clubelo.com/{Equipo}` para descargar historiales CSV con columnas
`Rank,Club,Country,Level,Elo,From,To`, guarda cada historial en
`data/raw/clubelo` y usa el rating del dia anterior al partido para evitar
filtracion temporal.

El modelo `club_elo` no reentrena nada localmente. Toma los ratings externos y
los transforma a probabilidades 1X2 con la misma conversion Elo simple usada por
el proyecto, para que la comparacion mida la fuerza de la senal externa con una
calibracion comparable.

Estado validado del 2026-08-27: la cache local quedo completa con 161/161
historiales. Se agregaron aliases especificos para `Ath Bilbao` -> `Bilbao` y
`Nurnberg` -> `Nuernberg`; ademas, un timeout por candidato ya no cancela toda
la busqueda de un equipo.

La cobertura offline quedo en 17,937/17,937 partidos, sin equipos faltantes:

```text
loaded_teams=161
missing_teams=0
matches=17937
predicted_matches=17937
skipped_matches=0
coverage=1.0000
```

La comparacion completa ya fue persistida en `model_versions` y
`model_metrics`. En la metrica principal, `club_elo` quedo muy cerca de
`elo_simple`, pero aun por detras de `market_avg_odds`.

## Siguiente paso

Con los baselines cerrados, el siguiente trabajo natural es Fase 5:
automatizar congelado semanal, reentrenamiento walk-forward y promocion de
modelo campeon.
