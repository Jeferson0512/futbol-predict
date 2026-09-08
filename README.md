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
cd E:\Trabajos\Propios\futbol-predict
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
cd E:\Trabajos\Propios\futbol-predict
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
cd E:\Trabajos\Propios\futbol-predict\backend
uv sync --extra dev
uv run pytest
uv run uvicorn futpredict.main:app --reload
```

Para usar PostgreSQL desde el backend local, define `DATABASE_URL` con el host
accesible desde Windows. Si PostgreSQL viene de Docker Compose, normalmente el
host local sera `localhost`; dentro de Docker Compose el host sera `postgres`.

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli db-status
```

## Ingesta inicial gratuita

La fuente recomendada para empezar es `football-data.co.uk`, porque publica
CSVs gratis con resultados historicos, estadisticas y cuotas.

Ejemplo:

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
uv run futpredict ingest-football-data-uk --season 2526 --division E0
```

`2526` representa la temporada 2025/26 y `E0` la Premier League.

Tambien puedes guardar el CSV en cache y correr el primer backtest local:

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
.\.venv\Scripts\python.exe -m futpredict.cli download-football-data-uk --season 2526 --division E0
.\.venv\Scripts\python.exe -m futpredict.cli backtest-football-data-uk --season 2526 --division E0
```

La salida compara `always_home`, `historical_frequency`, `elo_simple` y
`market_avg_odds` cuando el CSV trae cuotas 1X2. El lector prioriza cuotas
promedio de cierre, luego promedio pre-partido, promedio historico `BbAv*`,
Pinnacle y Bet365 como fallback. Se reporta RPS, log-loss, Brier y accuracy.

Para descargar y evaluar Big-5 en diez temporadas:

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
.\.venv\Scripts\python.exe -m futpredict.cli download-big-five --start-season 1617 --end-season 2526
.\.venv\Scripts\python.exe -m futpredict.cli backtest-big-five --start-season 1617 --end-season 2526
```

La API expone el agregado y sus desgloses por liga y temporada:

```text
GET /backtests/football-data-uk/big-five?start_season=1617&end_season=2526
```

Para preparar y cargar esos datos a PostgreSQL:

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli load-big-five-db --start-season 1617 --end-season 2526 --dry-run
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m futpredict.cli load-big-five-db --start-season 1617 --end-season 2526
.\.venv\Scripts\python.exe -m futpredict.cli team-aliases-status
```

Para evaluar desde PostgreSQL, sin volver a leer los CSV:

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli backtest-db-football-data-uk --season 2526 --division E0
.\.venv\Scripts\python.exe -m futpredict.cli backtest-db-big-five --start-season 1617 --end-season 2526
```

Para generar features historicos con fecha de corte:

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli build-rolling-features-db --start-season 1617 --end-season 2526 --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli build-rolling-features-db --start-season 1617 --end-season 2526
.\.venv\Scripts\python.exe -m futpredict.cli features-status
```

Para persistir Elo propio por partido:

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli build-elo-ratings-db --start-season 1617 --end-season 2526 --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli build-elo-ratings-db --start-season 1617 --end-season 2526
.\.venv\Scripts\python.exe -m futpredict.cli elo-ratings-status
```

Para ejecutar walk-forward formal y guardar metricas por ventana:

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
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
cd E:\Trabajos\Propios\futbol-predict\backend
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
cd E:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"
.\.venv\Scripts\python.exe -m futpredict.cli download-football-data-uk-fixtures --force
.\.venv\Scripts\python.exe -m futpredict.cli load-big-five-fixtures-db --season 2627 --force
.\.venv\Scripts\python.exe -m futpredict.cli fixtures-status
```

Para regenerar el contrato API del frontend:

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
.\.venv\Scripts\python.exe -m futpredict.cli export-openapi --output ..\frontend\src\api\openapi.json

cd E:\Trabajos\Propios\futbol-predict\frontend
npm run generate:api-types
```

## Fase 5 - Automatizacion

El pipeline semanal orquesta todos los pasos honestos en orden: reconstruye Elo
y features, re-corre el walk-forward, congela y evalua predicciones, reconstruye
calibracion, promueve el modelo campeon por RPS y congela las predicciones de la
proxima jornada. Todo respeta las reglas anti-leakage (`predicted_at < kickoff`,
registro inmutable).

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"

# Ver el plan completo sin escribir nada (rollback al final).
.\.venv\Scripts\python.exe -m futpredict.cli run-weekly --dry-run

# Ejecutar el pipeline real (commit por paso).
.\.venv\Scripts\python.exe -m futpredict.cli run-weekly

# Pasos individuales de Fase 5.
.\.venv\Scripts\python.exe -m futpredict.cli promote-champion --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli promote-champion
.\.venv\Scripts\python.exe -m futpredict.cli champion-status
.\.venv\Scripts\python.exe -m futpredict.cli freeze-future-predictions-db --days 14 --dry-run
.\.venv\Scripts\python.exe -m futpredict.cli freeze-future-predictions-db --days 14
```

### Backup automatico

Cada corrida de `run-daily` y `run-weekly` termina sacando un `pg_dump -Fc` a
`backups/postgres/auto/` y rotando los mas viejos (por defecto conserva 14).
Las predicciones congeladas son irreproducibles: la regla del proyecto prohibe
reescribir una prediccion historica, asi que un `freeze` perdido no se puede
regenerar sin romper la honestidad del registro.

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
.\.venv\Scripts\python.exe -m futpredict.cli backup-db
.\.venv\Scripts\python.exe -m futpredict.cli backup-db --list
.\.venv\Scripts\python.exe -m futpredict.cli backup-db --keep 30
```

Si `pg_dump` no esta en el PATH (tipico en Windows), define `PG_DUMP_PATH` en
`backend/.env` con la ruta al binario. La carpeta `auto/` esta ignorada por Git;
el dump de handoff versionado en `backups/postgres/` se sigue creando a mano.

El backup es best-effort: si falla no invalida el trabajo ya commiteado del
pipeline, pero queda reportado en el resumen final y `run-daily`/`run-weekly`
terminan con codigo 1 para que Windows Task Scheduler lo muestre.

El campeon se elige por RPS ponderado global y se marca exactamente una
`model_version` por liga (la de la ventana mas reciente), respetando el indice
`uq_one_champion_per_league`. Las predicciones futuras solo se congelan para
fixtures con `kickoff_utc` estrictamente posterior al momento de congelado, y
nunca sobrescriben una prediccion ya registrada.

Para que `freeze-future-predictions-db` tenga fixtures que congelar, primero hay
que cargar la jornada proxima con `load-big-five-fixtures-db --season <codigo>`.

## Fase 6 - ML tabular

El primer modelo entrenado real es una regresion logistica multinomial sobre el
feature set `rolling_v1`, evaluada con el mismo walk-forward temporal que los
baselines (entrena con temporadas previas, predice la de evaluacion, sin
leakage). Requiere el extra `ml`:

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
uv sync --extra dev --extra ml
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"

# Necesita features persistidas (build-rolling-features-db) para 'rolling_v1'.
.\.venv\Scripts\python.exe -m futpredict.cli backtest-ml-walk-forward-db --start-season 1617 --end-season 2526
```

La salida ordena por RPS ponderado los modelos ML junto a los baselines. Ademas
de la logistica hay gradient boosting (`HistGradientBoosting`) y calibracion
isotonica, y un feature set con xG (`rolling_v2`).

### xG desde Understat

Se descarga xG por partido desde Understat (via `soccerdata`), se guarda en
`matches` y se construye el feature set `rolling_v2` (rolling_v1 + xG rodante):

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"

# Validar el mapeo de equipos (Understat -> football-data) por cobertura.
.\.venv\Scripts\python.exe -m futpredict.cli understat-xg-coverage --division E0 --season 2324
.\.venv\Scripts\python.exe -m futpredict.cli load-understat-xg-big-five --start-season 1617 --end-season 2526 --dry-run

# Guardar xG, construir rolling_v2 y medir el impacto.
.\.venv\Scripts\python.exe -m futpredict.cli load-understat-xg-big-five --start-season 1617 --end-season 2526
.\.venv\Scripts\python.exe -m futpredict.cli build-rolling-features-db --start-season 1617 --end-season 2526 --with-xg
.\.venv\Scripts\python.exe -m futpredict.cli backtest-ml-walk-forward-db --start-season 1617 --end-season 2526 --feature-set rolling_v2
```

Medicion honesta: el xG mejora los tres modelos ML (logistica 0.216 -> 0.213,
boosting 0.222 -> 0.217), acercandolos a `elo_simple` (0.203) aunque todavia sin
superar a Elo ni al mercado. Ningun modelo ML es campeon aun; el mercado sigue
liderando por RPS.

## Modelo de goles (Dixon-Coles)

Familia distinta a la de los tabulares: en vez de features rodantes estima
fuerza de ataque y defensa por equipo mas ventaja local, y de ahi saca la matriz
de marcadores. Suma dos cosas sobre un Poisson plano: correccion de dependencia
en marcadores bajos (donde el Poisson independiente subestima empates) y
decaimiento temporal (los partidos viejos pesan menos).

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"

# Medir sin escribir (por defecto, las tres ligas sin cuotas).
.\.venv\Scripts\python.exe -m futpredict.cli backtest-goals-walk-forward-db

# Medir Big-5 y persistir metricas + predicciones congeladas.
.\.venv\Scripts\python.exe -m futpredict.cli backtest-goals-walk-forward-db --divisions E0,SP1,I1,D1,F1 --initial-train-seasons 3 --persist
```

**Medicion honesta (comparacion sobre los mismos partidos):** Dixon-Coles
**gana en las tres ligas sin cuotas** y es campeon en ellas — Peru 0,1929 vs
0,1977 de Elo, Brasil 0,2112 vs 0,2124, Argentina 0,2155 vs 0,2160. En los
Big-5 queda tercero (0,2063) por detras de Elo (0,2027) y del mercado (0,1960):
el mercado sigue siendo imbatible donde hay cuotas.

Dos limites que conviene tener presentes:

- El modelo **omite** los partidos con equipos que no vio entrenando (recien
  ascendidos): ~11% de los casos. Se salta la prediccion en vez de inventarla,
  igual que `market_avg_odds` cuando falta la cuota. Por eso su `n` es menor y
  los agregados no estan sobre el conjunto exacto de los baselines.
- Un ajuste degenerado (pocos equipos, marcadores sin varianza) devuelve `None`
  en vez de lanzar: no puede tumbar el pipeline ni un request del API.

## Altitud en la Liga 1 de Peru

En Liga 1 el desnivel entre sedes mueve el resultado mas que ningun otro factor
que los modelos vieran hasta ahora. Medido sobre 1.735 partidos (2021-2026), por
**valor absoluto** de la diferencia de altitud entre las ciudades sede:

```text
|diferencia|      n     %local   dif. goles
< 300 m          506     42.9%      +0.24
300-1000 m       266     45.5%      +0.41
1000-2000 m      122     45.9%      +0.28
2000-3000 m      408     52.7%      +0.71
> 3000 m         433     59.1%      +0.90
```

Referencia sin desnivel: Premier League 44.6% y +0.28 — igual que el tramo bajo.

**El efecto es simetrico y eso es lo que no se ve venir:** no es que la altura
favorezca al local, es que viajar a una altitud muy distinta perjudica al
visitante **en las dos direcciones**. Un equipo de Cusco visitando Lima sufre
casi tanto como uno de Lima visitando Cusco. Por eso la variable util es el
modulo del desnivel; con signo, los dos extremos se cancelan y la senal se
diluye.

`elo_altitude` (`models/altitude_elo.py`) deja el Elo intacto y solo hace
variable la ventaja local:

```text
ventaja_local = 65 + 60 * min(|desnivel_km|, 4)
```

```powershell
cd E:\Trabajos\Propios\futbol-predict\backend
$env:DATABASE_URL="postgresql+psycopg://futbol:futbol@localhost:5433/futbol_predict"

.\.venv\Scripts\python.exe -m futpredict.cli altitude-walk-forward-db
.\.venv\Scripts\python.exe -m futpredict.cli altitude-walk-forward-db --persist
```

**Medicion honesta.** Los dos parametros se eligieron por rejilla sobre
2021-2023 (temporadas de entrenamiento) y se evaluaron aparte en 2024-2026:
RPS **0.1893** frente a 0.1974 de `elo_simple`. Sobre todas las ventanas
disponibles y los mismos 1.201 partidos: **0.1882** vs 0.1985, con 54.9% de
acierto frente a 53.2%. Es el campeon de Liga 1 y **el mejor RPS de las ocho
ligas del proyecto**.

Control de correccion: con `advantage_per_km=0` el modelo reproduce
`elo_simple` hasta el ultimo decimal (diferencia 0.000000), asi que la ganancia
viene de la altitud y no de otro cambio colado.

Limites: las cifras son la altitud de la **ciudad sede**, no del cesped del
estadio, y no siguen a un club que cambia de sede a mitad de temporada. Fuera de
las ligas con tabla de altitudes el modelo se omite en vez de duplicar a
`elo_simple`.

## Reglas del proyecto

- Nunca usar split aleatorio para validar modelos de partidos.
- Toda feature debe declarar una fecha de corte.
- Ninguna prediccion puede registrarse con `predicted_at >= kickoff_utc`.
- Nunca sobrescribir una prediccion historica.
- El porcentaje de acierto solo sirve para comunicar, no para decidir.
- La metrica principal es RPS.

## Siguiente objetivo

Fases 5 (automatizacion) y 6 (ML tabular con xG) estan cerradas. Ningun modelo
ML supera aun a Elo ni al mercado; mejorarlos (mas features de xG, ajuste por
rival) es trabajo abierto. Siguen la Fase 7 (vista amigable de predicciones,
prototipo aprobado, pendiente de implementar en el frontend) y la Fase 8
(expansion a Brasil, Argentina y Liga 1 Peru).
