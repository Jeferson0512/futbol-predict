# Roadmap

## Fase 0 - Cimientos

- [x] Monorepo backend/frontend.
- [x] Docker Compose local.
- [x] FastAPI con healthcheck.
- [x] SQLAlchemy 2.0.
- [x] Alembic.
- [x] pytest, ruff y mypy configurados.
- [x] RPS y Elo iniciales.
- [x] CI en GitHub Actions.

## Fase 1 - Datos gratis

- [x] Adaptador inicial para `football-data.co.uk`.
- [x] Descarga cacheada de CSVs.
- [x] Parser normalizado a partidos de dominio.
- [x] Descargar Big-5 para 10 temporadas.
- [x] Comando CLI para descargar Big-5 por rango de temporadas.
- [x] Endpoint API para backtest Big-5 agregado.
- [x] Desglose por liga y temporada en API y dashboard.
- [x] Capa staging normalizada para preparar persistencia.
- [x] Upserts idempotentes hacia PostgreSQL implementados.
- [x] Ejecutar migraciones contra PostgreSQL local.
- [x] Persistir ligas, equipos, temporadas y partidos.
- [x] Cargar cuotas 1X2 cuando existan.
- [x] Resolver aliases de equipos.
- [x] Validar duplicados y conteos por temporada.
- [x] Backtests leyendo desde PostgreSQL.
- [x] Primer feature set historico con fecha de corte.

## Fase 2 - Baselines

- [x] Siempre local.
- [x] Frecuencias historicas de liga.
- [x] Backtest inicial siempre local, frecuencias historicas y Elo simple.
- [x] Baseline `market_avg_odds` quitando margen de cuotas promedio.
- [x] Fallback de cuotas para temporadas antiguas (`AvgC*`, `Avg*`, `BbAv*`, Pinnacle, Bet365).
- [x] Elo propio persistido por partido.
- [x] Backtest walk-forward.
- [x] Comparacion contra Club Elo.
  - [x] Adaptador cacheado de historiales Club Elo.
  - [x] Soporte opcional de `club_elo` en walk-forward.
  - [x] Comando de cobertura contra PostgreSQL.
  - [x] Ejecutar comparacion completa con cache local completa.
- [x] Persistencia de metricas agregadas por baseline y ventana.

## Fase 3 - Medicion

- [x] Registro inmutable de predicciones.
- [x] Evaluador post-partido.
- [x] RPS, log-loss y Brier por modelo.
- [x] Curvas de calibracion.
- [x] MLflow para versiones y artefactos.

## Fase 4 - API y SPA

- [x] Endpoints de fixtures.
- [x] Endpoint de estado de predicciones.
- [x] Endpoints de metricas y calibracion.
- [x] Endpoint de modelo campeon por RPS.
- [x] Endpoint de predicciones futuras transitorias.
- [x] Generacion de tipos desde OpenAPI.
- [x] Dashboard React con tablas y graficos historicos.
- [x] Vista de predicciones futuras por fixture.

## Fase 5 - Automatizacion

- [ ] Job semanal.
- [ ] Reentrenamiento walk-forward.
- [ ] Promocion de modelo campeon por RPS.
- [ ] Predicciones congeladas de la siguiente fecha.

## Fase 6 - ML tabular

- [x] Primer set de features temporales anti-leakage.
- [ ] xG desde Understat via soccerdata.
- [ ] Regresion logistica multinomial.
- [ ] XGBoost o LightGBM.
- [ ] Calibracion Platt/isotonica.

## Fase 7 - Expansion

- [ ] Brasil.
- [ ] Argentina.
- [ ] Liga 1 Peru.
- [ ] Ajuste de parametros por liga.
