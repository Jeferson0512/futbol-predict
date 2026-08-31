# Fase 1 - Persistencia y carga normalizada

Objetivo: pasar de CSVs y backtests en memoria a datos auditables, repetibles y listos
para PostgreSQL. Esta fase no busca mejorar el modelo todavia; busca que los datos queden
bien preparados para cualquier modelo posterior.

## Checklist de trabajo

- [x] Fuente gratuita principal definida: `football-data.co.uk`.
- [x] Cache local de Big-5 por temporadas.
- [x] Parser a partidos de dominio con cuotas 1X2 disponibles.
- [x] Capa staging para ligas, temporadas, equipos, partidos y cuotas.
- [x] Validacion de duplicados, cuotas faltantes y registros huerfanos.
- [x] CLI de inspeccion para una liga/temporada y para Big-5 completo.
- [x] Upserts idempotentes a PostgreSQL implementados.
- [x] Dry-run de carga validado para Premier 25/26 y Big-5 1617-2526.
- [x] Ejecutar migraciones Alembic contra PostgreSQL local.
- [x] Carga real de ligas, temporadas, equipos, partidos y cuotas a BD.
- [x] Tabla normalizada de aliases de equipos.
- [x] Validacion contra conteos esperados por liga/temporada despues de cargar BD.
- [x] CLI de backtest leyendo desde PostgreSQL.
- [x] API de backtest leyendo desde PostgreSQL.
- [x] Primer feature set historico `rolling_v1` con fecha de corte.
- [x] Documentar comandos finales de carga y auditoria.

## Orden para cerrar la fase

1. Normalizar los datos en memoria con claves naturales estables.
2. Auditar Big-5 completo: conteos, duplicados y cobertura de cuotas.
3. Implementar upserts idempotentes hacia las tablas actuales.
4. Cargar una temporada de prueba y verificar conteos.
5. Cargar Big-5 completo desde cache.
6. Exponer consultas API basadas en BD en lugar de leer CSV directo.
7. Dejar pruebas automaticas para normalizacion y carga.

## Comandos de trabajo

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli inspect-normalized-football-data-uk --season 2526 --division E0
.\.venv\Scripts\python.exe -m futpredict.cli inspect-normalized-big-five --start-season 1617 --end-season 2526
.\.venv\Scripts\python.exe -m futpredict.cli load-football-data-uk-db --season 2526 --division E0 --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli load-big-five-db --start-season 1617 --end-season 2526 --dry-run
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m futpredict.cli load-football-data-uk-db --season 2526 --division E0
.\.venv\Scripts\python.exe -m futpredict.cli load-big-five-db --start-season 1617 --end-season 2526
.\.venv\Scripts\python.exe -m futpredict.cli team-aliases-status
.\.venv\Scripts\python.exe -m futpredict.cli backtest-db-football-data-uk --season 2526 --division E0
.\.venv\Scripts\python.exe -m futpredict.cli backtest-db-big-five --start-season 1617 --end-season 2526
.\.venv\Scripts\python.exe -m futpredict.cli build-rolling-features-db --start-season 1617 --end-season 2526 --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli build-rolling-features-db --start-season 1617 --end-season 2526
.\.venv\Scripts\python.exe -m futpredict.cli features-status
```

## Endpoints de auditoria

```text
GET /backtests/db/football-data-uk?season=2526&division=E0
GET /backtests/db/big-five?start_season=1617&end_season=2526
```

## Estado actual

Estado del 2026-08-26: Docker Desktop quedo operativo con WSL2. Como ya existe un
PostgreSQL local en `localhost:5432`, el PostgreSQL del proyecto se publica en
`localhost:5433`. Las migraciones Alembic quedaron en
`0003_team_aliases` y Big-5 1617-2526 quedo cargado con estos conteos: 5 ligas,
50 temporadas, 161 equipos, 161 aliases, 17,937 partidos y 17,937 cuotas.

El backtest desde PostgreSQL para Big-5 1617-2526 quedo validado con 17,937
partidos. El mejor baseline actual es `market_avg_odds`, seguido por
`elo_simple`; esta referencia sirve como piso antes de entrenar modelos nuevos.

Con esto, Fase 1 deja los datos historicos en una forma auditable: dimensiones
normalizadas, aliases consultables, upserts idempotentes, backtests leyendo
desde la base y un primer feature set `rolling_v1`.

Estado de features validado:

```text
feature_set_version,features,first_cutoff,last_cutoff
rolling_v1,17937,2016-08-12 00:00:00+00:00,2026-05-24 20:00:00+00:00
```
