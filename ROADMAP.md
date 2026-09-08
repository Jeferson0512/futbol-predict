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

- [x] Job semanal orquestado (`run-weekly`, modulo `jobs/weekly.py`).
- [x] Reentrenamiento walk-forward dentro del job.
- [x] Promocion de modelo campeon por RPS (`promote-champion`, un campeon por liga).
- [x] Predicciones congeladas de la siguiente fecha (`freeze-future-predictions-db`).
- [x] Programacion automatica (Windows Task Scheduler: diario 07:00, semanal lunes 08:00).
- [x] Backup rotativo automatico al final de cada corrida (`backup-db`).

## Fase 6 - ML tabular

- [x] Primer set de features temporales anti-leakage.
- [x] Regresion logistica multinomial (`backtest-ml-walk-forward-db`).
- [x] xG desde Understat via soccerdata (feature set `rolling_v2`, cobertura 100%).
- [x] Gradient boosting (HistGradientBoosting; XGBoost/LightGBM opcional a futuro).
- [x] Calibracion Platt/isotonica.

## Fase 7 - Vista amigable de predicciones

App React "Pronosticos" (toggle con el panel analitico), 5 vistas:

- [x] Proximos: pestanas por liga (Big-5) + tarjetas 1X2 con pronostico recomendado.
- [x] Resultados/Historial: aciertos/fallos por partido + resumen (endpoint `/predictions/history`).
- [x] Calibracion amigable (reliability diagram sobre `/calibration/curves`).
- [x] Comparador de modelos por RPS (`/models/rankings`).
- [x] Ficha de partido: forma, xG, Elo, cuota, cara a cara (endpoint `/matches/{id}`).

## Fase 8 - Expansion

- [x] Liga 1 Peru (ESPN).
- [x] Brasil (ESPN).
- [x] Argentina (ESPN).
- [x] Job diario separado del semanal.
- [x] Campeon por liga (no uno global).
- [x] xG (Understat) integrado al job semanal.
- [x] Ajuste de parametros por liga: ventaja local por altitud en PER1 (`elo_altitude`).
- [ ] Ajustar tambien k y la tasa de empate por liga (Argentina empata mucho mas).

## Fase 9 - Cuotas frescas y cobertura

- [x] Resultados usa el modelo fresco por liga.
- [x] Brasil y Argentina via ESPN.
- [ ] Cuotas de la temporada en curso (requiere plan de pago; decision del usuario).

## Fase 10 - Modelo de goles

- [x] Dixon-Coles sobre `penaltyblog` (`models/poisson.py`).
- [x] Walk-forward propio con las mismas garantias anti-leakage.
- [x] Compite por campeon y congela historial (campeon en PER1, BRA1 y ARG1).
- [x] Integrado al job semanal y a las predicciones futuras.
- [ ] Marcador exacto y over/under en la app (la matriz de goles ya se calcula).

## Fase 11 - Altitud

- [x] Tabla de altitudes de las 28 sedes de Liga 1 (cobertura 100%).
- [x] `elo_altitude`: ventaja local en funcion del modulo del desnivel.
- [x] Parametros calibrados solo con temporadas de entrenamiento.
- [x] Campeon de Liga 1 Peru (RPS 0.1882, el mejor de las 8 ligas).
- [ ] Extender a otras ligas de altitud (Bolivia, Ecuador, Colombia).
