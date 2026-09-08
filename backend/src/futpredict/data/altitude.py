"""Altitud de las sedes de la Liga 1 de Peru.

Motivo: en Liga 1 el desnivel entre sedes mueve el resultado mucho mas que en
Europa, y ningun modelo del proyecto lo ve. Medido sobre 1.735 partidos
(2021-2026), agrupando por **valor absoluto** de la diferencia de altitud:

    |diferencia|      n     %local   dif. goles
    < 300 m          506     42.9%      +0.24
    300-1000 m       266     45.5%      +0.41
    1000-2000 m      122     45.9%      +0.28
    2000-3000 m      408     52.7%      +0.71
    > 3000 m         433     59.1%      +0.90

Referencia sin desnivel: Premier League 44.6% y +0.28.

**El efecto es simetrico**, y esto es lo que no se ve venir: no es que la altura
favorezca al local, es que **viajar a una altitud muy distinta perjudica al
visitante en las dos direcciones**. Un equipo de Cusco visitando Lima sufre casi
tanto como uno de Lima visitando Cusco (58.1% local con el local en la costa,
54.1% con el local en la sierra). Por eso la feature util es el modulo del
desnivel, no su signo; con signo, los dos extremos se cancelan.

Las cifras son la altitud aproximada de la **ciudad sede**, no del cesped del
estadio, y no siguen a un club que cambia de sede a mitad de temporada. Es
suficiente para una variable que se usa por tramos de cientos de metros.
"""

from __future__ import annotations

# Altitud aproximada (metros sobre el nivel del mar) de la ciudad de cada club.
PERU_TEAM_ALTITUDE_M: dict[str, int] = {
    "ADT": 3053,  # Tarma
    "Academia Cantolao": 5,  # Callao
    "Alianza Atlético": 60,  # Sullana
    "Alianza Lima": 154,  # Lima
    "Alianza Universidad": 1912,  # Huanuco
    "Atlético Grau": 29,  # Piura
    "Ayacucho FC": 2761,  # Ayacucho
    "Carlos A. Mannucci": 34,  # Trujillo
    "Carlos Stein": 27,  # Lambayeque
    "Cienciano del Cusco": 3399,  # Cusco
    "Comerciantes Unidos": 2637,  # Cutervo
    "Cusco FC": 3399,  # Cusco
    "César Vallejo": 34,  # Trujillo
    "Deportivo Binacional": 3825,  # Juliaca
    "Deportivo Garcilaso": 3399,  # Cusco
    "Deportivo Moquegua": 1410,  # Moquegua
    "Deportivo Municipal": 154,  # Lima
    "FC Cajamarca": 2750,  # Cajamarca
    "Juan Pablo II": 230,  # Chongoyape
    "Los Chankas": 2926,  # Andahuaylas
    "Melgar": 2335,  # Arequipa
    "San Martin": 154,  # Lima
    "Sport Boys": 5,  # Callao
    "Sport Huancayo": 3271,  # Huancayo
    "Sporting Cristal": 154,  # Lima
    "UTC": 2750,  # Cajamarca
    "Unión Comercio": 860,  # Nueva Cajamarca
    "Universitario": 154,  # Lima
}

# Ligas cuyas sedes tienen desnivel relevante. Las europeas y las de Brasil y
# Argentina juegan practicamente todas cerca del nivel del mar.
ALTITUDE_DIVISIONS: frozenset[str] = frozenset({"PER1"})

ALTITUDE_BY_DIVISION: dict[str, dict[str, int]] = {"PER1": PERU_TEAM_ALTITUDE_M}


def team_altitude_m(team: str, division: str) -> int | None:
    """Altitud de la sede de un equipo, o `None` si no se conoce."""
    table = ALTITUDE_BY_DIVISION.get(division)
    if table is None:
        return None
    return table.get(team)


def altitude_gap_m(home_team: str, away_team: str, division: str) -> int | None:
    """Modulo del desnivel entre las dos sedes, o `None` si falta alguna.

    Se devuelve en valor absoluto a proposito: el efecto medido es simetrico
    (ver el docstring del modulo). Usar el desnivel con signo mezcla los dos
    extremos, que empujan en la misma direccion, y diluye la senal.
    """
    home = team_altitude_m(home_team, division)
    away = team_altitude_m(away_team, division)
    if home is None or away is None:
        return None
    return abs(home - away)


def altitude_coverage(
    pairs: list[tuple[str, str, str]],
) -> tuple[int, int, list[str]]:
    """(con altitud, total, equipos sin altitud) para auditar la cobertura."""
    known = 0
    missing: set[str] = set()
    for home, away, division in pairs:
        if division not in ALTITUDE_BY_DIVISION:
            continue
        if altitude_gap_m(home, away, division) is not None:
            known += 1
            continue
        for team in (home, away):
            if team_altitude_m(team, division) is None:
                missing.add(team)
    total = sum(1 for _home, _away, division in pairs if division in ALTITUDE_BY_DIVISION)
    return known, total, sorted(missing)


def division_has_altitude(division: str) -> bool:
    """Si la division tiene tabla de altitudes.

    Fuera de ellas el ajuste seria identico a `elo_simple`, asi que el modelo
    se omite en vez de duplicar un baseline que ya existe.
    """
    return division in ALTITUDE_BY_DIVISION
