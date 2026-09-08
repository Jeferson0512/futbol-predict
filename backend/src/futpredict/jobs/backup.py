"""Backup rotativo de PostgreSQL para el pipeline.

Las predicciones congeladas son **irreproducibles**: la regla del proyecto
prohibe reescribir una prediccion historica, asi que un `freeze` perdido no se
puede regenerar sin romper la honestidad del registro. Por eso el job saca un
`pg_dump -Fc` al final de cada corrida y mantiene solo los ultimos N.

El dump automatico va a `backups/postgres/auto/` (ignorado por Git); el dump
de handoff versionado en `backups/postgres/` se sigue creando a mano.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

BACKUP_PREFIX = "futbol_predict_"
BACKUP_SUFFIX = ".dump"
DEFAULT_KEEP = 14
_DEFAULT_PG_DUMP = "pg_dump"


class BackupError(RuntimeError):
    """El backup no se pudo completar."""


@dataclass(frozen=True)
class BackupResult:
    path: Path
    size_bytes: int
    removed: tuple[Path, ...]

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


def default_backup_dir() -> Path:
    """`backups/postgres/auto/` en la raiz del repo, sea cual sea el CWD."""
    # backend/src/futpredict/jobs/backup.py -> parents[4] es la raiz del repo.
    return Path(__file__).resolve().parents[4] / "backups" / "postgres" / "auto"


def backup_filename(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}"


def libpq_dsn(database_url: str) -> tuple[str, str | None]:
    """Convierte la URL de SQLAlchemy en un DSN de libpq sin contrasena.

    Devuelve `(dsn, password)`. La contrasena se saca de la URL a proposito para
    pasarla por `PGPASSWORD` y no dejarla visible en la linea de comandos.
    """
    parts = urlsplit(database_url)
    if not parts.scheme:
        msg = f"URL de base de datos invalida: {database_url!r}"
        raise BackupError(msg)
    # `postgresql+psycopg` -> `postgresql`; pg_dump no entiende el driver.
    scheme = parts.scheme.split("+", 1)[0]
    if scheme not in {"postgres", "postgresql"}:
        msg = f"solo se puede respaldar PostgreSQL, no {scheme!r}"
        raise BackupError(msg)

    password = parts.password
    host = parts.hostname or "localhost"
    netloc = f"{parts.username}@{host}" if parts.username else host
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((scheme, netloc, parts.path, "", "")), password


def pg_dump_command(dsn: str, output: Path, pg_dump_path: str | None = None) -> list[str]:
    return [
        pg_dump_path or _DEFAULT_PG_DUMP,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        f"--file={output}",
        "--dbname",
        dsn,
    ]


def existing_backups(directory: Path) -> list[Path]:
    """Dumps automaticos del directorio, del mas nuevo al mas viejo."""
    if not directory.is_dir():
        return []
    found = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.name.startswith(BACKUP_PREFIX) and path.suffix == BACKUP_SUFFIX
    ]
    # El nombre lleva el timestamp, asi que ordenar por nombre basta y no
    # depende de mtime (que un copiado de archivos puede alterar).
    return sorted(found, key=lambda path: path.name, reverse=True)


def rotate_backups(directory: Path, keep: int) -> list[Path]:
    """Borra los dumps mas viejos y devuelve los eliminados."""
    if keep < 1:
        msg = "keep debe ser positivo"
        raise BackupError(msg)
    removed: list[Path] = []
    for stale in existing_backups(directory)[keep:]:
        stale.unlink()
        removed.append(stale)
    return removed


def _run_pg_dump(command: Sequence[str], env: Mapping[str, str]) -> None:
    try:
        completed = subprocess.run(  # noqa: S603 - comando construido aqui, sin shell
            list(command),
            env=dict(env),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        msg = (
            f"no se encontro '{command[0]}'. Instala las herramientas de cliente de "
            "PostgreSQL o define PG_DUMP_PATH con la ruta al binario."
        )
        raise BackupError(msg) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        msg = f"pg_dump fallo con codigo {completed.returncode}: {detail}"
        raise BackupError(msg)


def create_database_backup(
    database_url: str,
    *,
    out_dir: Path | None = None,
    keep: int = DEFAULT_KEEP,
    now: datetime | None = None,
    pg_dump_path: str | None = None,
    runner: object | None = None,
) -> BackupResult:
    """Saca un `pg_dump -Fc` y rota los antiguos.

    `runner` permite inyectar un doble en los tests; por defecto ejecuta
    `pg_dump` de verdad.
    """
    directory = out_dir if out_dir is not None else default_backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / backup_filename(now)

    dsn, password = libpq_dsn(database_url)
    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = password

    command = pg_dump_command(dsn, output, pg_dump_path)
    execute = runner if runner is not None else _run_pg_dump
    execute(command, env)  # type: ignore[operator]

    if not output.is_file():
        msg = f"pg_dump termino sin errores pero no genero {output}"
        raise BackupError(msg)
    size = output.stat().st_size
    if size == 0:
        output.unlink()
        msg = "pg_dump genero un archivo vacio"
        raise BackupError(msg)

    removed = rotate_backups(directory, keep)
    return BackupResult(path=output, size_bytes=size, removed=tuple(removed))
