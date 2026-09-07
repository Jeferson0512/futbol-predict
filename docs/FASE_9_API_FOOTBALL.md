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

## Plan (cuadro)

| # | Tarea | Qué resuelve | Estado |
|---|-------|--------------|:------:|
| A | Frontend: Resultados usa el modelo fresco (`elo_simple`) por defecto | Historial de Europa deja de verse viejo **ya** | ⬜ |
| B | Adaptador `providers/api_football.py` (fixtures + resultados + odds) + key en `.env` | Fuente única fresca **con cuotas** | ⬜ |
| C | Cargar odds de API-Football → el mercado predice la temporada en curso | El campeón (market) vuelve a estar fresco en Europa | ⬜ |
| D | Enganchar API-Football al job diario/semanal (con control de rate-limit) | Todo se actualiza solo | ⬜ |
| E | Brasil / Argentina vía API-Football | Cobertura nueva (Prio 3 restante) | ⬜ |
| F | (Opc.) Consolidar fuentes: API-Football principal, ESPN/football-data respaldo | Simplifica mantenimiento | ⬜ |

## Notas de seguridad y límites

- **API key es secreto:** vive en `backend/.env` (gitignored), NUNCA commiteada.
  Se recomienda al usuario **rotar** la key que quedó visible en pantalla.
- **Tier tester = ~100 requests/día:** dosificar; no barrer todas las ligas cada
  corrida. El job debe pedir solo lo nuevo (temporada en curso, ventana corta).
- Cada paso: rama → CI → merge (patrón del repo).
