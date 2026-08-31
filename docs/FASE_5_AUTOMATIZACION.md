# Fase 5 - Automatizacion

Objetivo: orquestar en un solo job semanal todo el ciclo honesto (reentrenar,
medir, congelar predicciones, promover campeon) para que el sistema se mantenga
al dia sin pasos manuales, respetando siempre las reglas anti-leakage.

## Checklist de trabajo

- [x] Job semanal orquestado (`jobs/weekly.py`, CLI `run-weekly`).
- [x] Reentrenamiento walk-forward dentro del job.
- [x] Promocion de modelo campeon por RPS (CLI `promote-champion`).
- [x] Predicciones congeladas de la siguiente fecha (CLI `freeze-future-predictions-db`).
- [ ] Programacion automatica (Windows Task Scheduler / cron / GitHub Actions).

## Pipeline semanal

`run-weekly` ejecuta estos pasos en orden, cada uno con commit propio (en
`--dry-run` calcula todo y hace rollback al final):

1. `rebuild_elo` - recalcula y persiste el Elo propio por partido.
2. `rebuild_features` - recalcula el feature set con fecha de corte.
3. `walk_forward_metrics` - re-corre el walk-forward y guarda metricas por ventana.
4. `freeze_walk_forward_predictions` - congela predicciones historicas inmutables.
5. `evaluate_predictions` - evalua las que ya tienen resultado (RPS, log-loss, Brier).
6. `build_calibration_bins` - reconstruye curvas de calibracion.
7. `promote_champion` - marca el campeon por RPS ponderado.
8. `freeze_future_predictions` - congela predicciones de la proxima jornada.

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli run-weekly --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli run-weekly
```

## Promocion del campeon por RPS

`promote-champion` toma el modelo con menor RPS ponderado global (agregando todas
las ventanas walk-forward en `model_metrics`) y marca `is_champion=true` en
exactamente una `model_version` por liga: la de la ventana de entrenamiento mas
reciente. La base impone un unico campeon por liga mediante el indice parcial
`uq_one_champion_per_league`, por eso el comando primero desmarca a todos los
campeones vigentes y luego promueve uno por liga.

```powershell
.\.venv\Scripts\python.exe -m futpredict.cli promote-champion --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli promote-champion
.\.venv\Scripts\python.exe -m futpredict.cli champion-status
```

## Predicciones congeladas de la proxima jornada

`freeze-future-predictions-db` construye predicciones para los fixtures cuyo
`kickoff_utc` es estrictamente posterior al momento de congelado, usando solo
partidos terminados antes de ese instante como entrenamiento. Registra cada
prediccion de forma inmutable (`predicted_at < kickoff_utc`, sin sobrescribir
predicciones existentes) para cada modelo soportado, de modo que luego el mismo
`evaluate-predictions-db` las evalua cuando llega el resultado.

```powershell
.\.venv\Scripts\python.exe -m futpredict.cli load-big-five-fixtures-db --season 2627 --force
.\.venv\Scripts\python.exe -m futpredict.cli freeze-future-predictions-db --days 14 --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli freeze-future-predictions-db --days 14
```

Si no hay fixtures con `kickoff_utc` futuro, el comando reporta
`eligible_fixtures=0` y no escribe nada; primero hay que cargar la jornada con
`load-big-five-fixtures-db`.

## Pendiente: programacion automatica

Falta decidir e implementar como se dispara el job cada semana. Opciones:

- Windows Task Scheduler apuntando a `run-weekly` (natural en esta PC sin Docker).
- Cron dentro de un contenedor (cuando se use Docker en otro entorno).
- GitHub Actions programado.

Tambien queda definir la fuente de refresco de fixtures futuros (hoy
`football-data.co.uk`).
