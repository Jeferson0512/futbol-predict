# Fase 4 - API y SPA

Objetivo: exponer la medicion historica persistida por API y mostrarla en una
SPA local para inspeccionar modelos, predicciones evaluadas y calibracion.

## Checklist de trabajo

- [x] Endpoints de fixtures.
- [x] Endpoint de estado de predicciones.
- [x] Endpoints de metricas y calibracion.
- [x] Endpoint de modelo campeon por RPS.
- [x] Endpoint de predicciones futuras transitorias.
- [x] Generacion de tipos desde OpenAPI.
- [x] Dashboard React con tablas y graficos historicos.
- [x] Vista de predicciones futuras por fixture.

## Endpoints actuales

```text
GET /health
GET /backtests/db/football-data-uk?season=2526&division=E0
GET /backtests/db/big-five?start_season=1617&end_season=2526
GET /predictions/status
GET /calibration/status?bins=10
GET /calibration/curves?bins=10&model=market_avg_odds
GET /models/rankings
GET /models/champion
GET /fixtures/upcoming?days=21&limit=40
GET /fixtures/predictions?days=21&limit=40&model=best_available
```

Los endpoints `/predictions/status`, `/calibration/status` y
`/calibration/curves` leen desde PostgreSQL. Por eso requieren que las
migraciones esten aplicadas y que existan predicciones congeladas, evaluadas y
bins de calibracion.

Los endpoints `/fixtures/upcoming` y `/fixtures/predictions` tambien leen desde
PostgreSQL. Los fixtures se alimentan desde el archivo semanal gratuito:

```text
https://www.football-data.co.uk/fixtures.csv
```

Ese archivo trae fixtures proximos y cuotas 1X2 cuando estan disponibles. El
endpoint de predicciones usa `best_available`: intenta ordenar los modelos por
RPS historico y elige el mejor modelo que pueda producir probabilidad para cada
fixture. Si el fixture no trae cuotas, `market_avg_odds` no aparece y puede
quedar `elo_simple` como mejor disponible.

## Dashboard

El frontend de Vite/React se sirve por HTTP en:

```text
http://localhost:5173
```

La pantalla principal consume datos reales de la API local:

- resumen del backtest Premier 25/26 o Big-5 historico;
- tabla de predicciones congeladas y evaluadas por modelo;
- tabla de calibracion por modelo;
- curva de calibracion por resultado local/empate/visita;
- tabla de proximos partidos con probabilidad 1X2 recomendada;
- desgloses por liga y temporada.

## Carga de fixtures

Desde Windows:

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli download-football-data-uk-fixtures --force
.\.venv\Scripts\python.exe -m futpredict.cli load-big-five-fixtures-db --season 2627 --force --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli load-big-five-fixtures-db --season 2627 --force
.\.venv\Scripts\python.exe -m futpredict.cli fixtures-status
```

Desde Docker:

```powershell
cd E:\Trabajos\Propios\futbol-predict
docker compose exec api python -m futpredict.cli load-big-five-fixtures-db --season 2627 --force
docker compose exec api python -m futpredict.cli fixtures-status
```

## Comandos de verificacion

Para regenerar el contrato API usado por React:

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
.\.venv\Scripts\python.exe -m futpredict.cli export-openapi --output ..\frontend\src\api\openapi.json

cd E:\Trabajos\Propios\futbol-predict\frontend
npm run generate:api-types
```

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
.\.venv\Scripts\ruff.exe check . --no-cache
.\.venv\Scripts\mypy.exe src --cache-dir C:\Users\Jeferson\AppData\Local\Temp\futpredict-mypy-cache
.\.venv\Scripts\pytest.exe

cd E:\Trabajos\Propios\futbol-predict\frontend
npm run build
```

## Estado para entrar a Fase 5

El dashboard actual muestra evaluacion historica y predicciones futuras
transitorias. Para pasar a Fase 5 falta congelar esas predicciones antes del
partido en la tabla `predictions`, programar el job semanal y promover el modelo
campeon de manera automatica.

La mini-fase 4.5 dejo listo el contrato backend/frontend: FastAPI exporta
`frontend/src/api/openapi.json`, el frontend genera `frontend/src/api/generated.ts`
y `main.tsx` consume esos tipos generados.

Antes de entrar a Fase 5 tambien quedaron cerrados los pendientes de Club Elo y
MLflow: `club_elo` tiene cobertura historica completa, predicciones congeladas,
metricas/calibracion, y las 175 versiones de modelo estan enlazadas a MLflow.
