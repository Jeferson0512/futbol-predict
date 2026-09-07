# Fase 9 — API-Football (cuotas frescas) + cierre de cobertura

Plan acordado con el usuario (2026-09-07). Se ejecuta en modo autónomo.

## Problema que resuelve

La vista **Resultados/Historial de Europa** se ve desactualizada: usa el campeón
`market_avg_odds`, pero los partidos de la temporada en curso (26/27) vienen de
ESPN **sin cuotas**, así que el mercado no puede predecirlos y el historial se
queda congelado en mayo-2026. `elo_simple` sí está fresco (no necesita cuotas).

La raíz es la **falta de cuotas** en la temporada en curso. `API-Football`
(`v3.football.api-sports.io`) trae fixtures + resultados + **cuotas** + stats de
la temporada en curso para Big-5, Brasil, Argentina y Perú.

## HALLAZGO IMPORTANTE (2026-09-07): el plan Free de API-Football NO sirve para el objetivo

Probado con la key real (`/status` OK, plan Free, 100 req/día):
- **La temporada en curso (2026) está bloqueada:** `"Free plans do not have access
  to this season, try from 2022 to 2024."`
- Los parámetros `last`/`next` están bloqueados en Free.
- Para un fixture accesible de 2022, el endpoint `/odds` devolvió **0 resultados**.

Conclusión: **las cuotas frescas (el motivo de B/C) requieren plan de pago.** En
gratis, API-Football solo duplicaría fixtures que ya tenemos de ESPN. Por eso se
**pivotó a E vía ESPN** (gratis, patrón Perú), que es la expansión de cobertura
real, y B/C quedan **en espera de una decisión de plan de pago** del usuario.

## Plan (cuadro)

| # | Tarea | Qué resuelve | Estado |
|---|-------|--------------|:------:|
| A | Frontend: Resultados usa el modelo fresco (`elo_simple`) por defecto | Historial de Europa deja de verse viejo **ya** | ✅ PR #11 |
| B | Adaptador API-Football (fixtures + resultados + odds) | Fuente única fresca **con cuotas** | ⛔ Requiere plan de pago |
| C | Cargar odds → el mercado predice la temporada en curso | El campeón (market) vuelve a estar fresco en Europa | ⛔ Requiere plan de pago |
| D | Enganchar API-Football al job (rate-limit) | Todo se actualiza solo | ⏸️ Tras plan de pago |
| E | **Brasil / Argentina vía ESPN** (no API-Football) | Cobertura nueva (Prio 3 restante) | ✅ Hecho |
| F | (Opc.) Consolidar fuentes | Simplifica mantenimiento | ⏸️ Después |

### Qué decidir cuando vuelvas
1. ¿Pagar API-Football (o similar) para cuotas de la temporada en curso? Solo así
   B/C tienen sentido y el mercado vuelve a Europa actual. Mientras tanto, A deja
   Europa fresca con Elo (funciona, Elo 0.202 vs market 0.196 — muy cerca).
2. **Rotar la API key** que quedó visible en pantalla.

### E — Brasil/Argentina (hecho, vía ESPN, patrón Perú)
`db_espn_league.py` (loader genérico + configs BRAZIL/ARGENTINA), divisiones
`BRA1`/`ARG1` en el catálogo, slugs `bra.1`/`arg.1`. CLIs `load-espn-league-db` y
`espn-league-walk-forward-db --league brazil|argentina`. Validado walk-forward:
Brasil elo_simple **0.2120** (48.6% acierto), Argentina elo_simple **0.2157**
(42.6%, liga con muchos empates). Enganchado al job (`serving_divisions` +
`espn_calendar_leagues` en `ingest_espn`), campeón por-liga (elo_simple) y en el
frontend (`LEAGUES`). 8 ligas con campeón.

## Notas de seguridad y límites

- **API key es secreto:** vive en `backend/.env` (gitignored), NUNCA commiteada.
  Se recomienda al usuario **rotar** la key que quedó visible en pantalla.
- **Tier tester = ~100 requests/día:** dosificar; no barrer todas las ligas cada
  corrida. El job debe pedir solo lo nuevo (temporada en curso, ventana corta).
- Cada paso: rama → CI → merge (patrón del repo).
