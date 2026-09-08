from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from futpredict.jobs import backup
from futpredict.jobs.backup import BackupError

_URL = "postgresql+psycopg://futbol:secreto@localhost:5433/futbol_predict"


def _fake_runner(payload: bytes = b"dump") -> object:
    """Doble de pg_dump: escribe el archivo pedido y registra la llamada."""
    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(command: Sequence[str], env: Mapping[str, str]) -> None:
        calls.append((list(command), dict(env)))
        target = next(arg for arg in command if arg.startswith("--file="))
        Path(target.removeprefix("--file=")).write_bytes(payload)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_libpq_dsn_strips_driver_and_password() -> None:
    dsn, password = backup.libpq_dsn(_URL)

    assert dsn == "postgresql://futbol@localhost:5433/futbol_predict"
    assert password == "secreto"
    # La contrasena nunca debe viajar en el DSN: iria en la linea de comandos.
    assert "secreto" not in dsn


def test_libpq_dsn_keeps_default_host_and_no_user() -> None:
    dsn, password = backup.libpq_dsn("postgresql://localhost/futbol_predict")

    assert dsn == "postgresql://localhost/futbol_predict"
    assert password is None


def test_libpq_dsn_rejects_non_postgres() -> None:
    with pytest.raises(BackupError, match="solo se puede respaldar PostgreSQL"):
        backup.libpq_dsn("sqlite:///local.db")


def test_backup_filename_is_sortable_by_name() -> None:
    older = backup.backup_filename(datetime(2026, 9, 1, 8, 0, tzinfo=UTC))
    newer = backup.backup_filename(datetime(2026, 9, 8, 8, 0, tzinfo=UTC))

    assert older.startswith(backup.BACKUP_PREFIX)
    assert newer.endswith(backup.BACKUP_SUFFIX)
    assert older < newer


def test_pg_dump_command_uses_custom_format(tmp_path: Path) -> None:
    command = backup.pg_dump_command("postgresql://localhost/db", tmp_path / "x.dump")

    assert command[0] == "pg_dump"
    assert "--format=custom" in command
    assert f"--file={tmp_path / 'x.dump'}" in command


def test_pg_dump_command_honours_explicit_binary(tmp_path: Path) -> None:
    command = backup.pg_dump_command("postgresql://localhost/db", tmp_path / "x.dump", "C:/pg_dump")

    assert command[0] == "C:/pg_dump"


def test_existing_backups_ignores_other_files(tmp_path: Path) -> None:
    (tmp_path / f"{backup.BACKUP_PREFIX}20260901-080000.dump").write_bytes(b"a")
    (tmp_path / f"{backup.BACKUP_PREFIX}20260908-080000.dump").write_bytes(b"b")
    (tmp_path / "README.md").write_text("no soy un dump")
    (tmp_path / "otra_cosa.dump").write_bytes(b"c")

    found = backup.existing_backups(tmp_path)

    assert [path.name for path in found] == [
        f"{backup.BACKUP_PREFIX}20260908-080000.dump",
        f"{backup.BACKUP_PREFIX}20260901-080000.dump",
    ]


def test_existing_backups_on_missing_directory(tmp_path: Path) -> None:
    assert backup.existing_backups(tmp_path / "no-existe") == []


def test_rotate_backups_keeps_newest(tmp_path: Path) -> None:
    for day in range(1, 6):
        (tmp_path / f"{backup.BACKUP_PREFIX}2026090{day}-080000.dump").write_bytes(b"x")

    removed = backup.rotate_backups(tmp_path, keep=2)

    assert [path.name for path in removed] == [
        f"{backup.BACKUP_PREFIX}20260903-080000.dump",
        f"{backup.BACKUP_PREFIX}20260902-080000.dump",
        f"{backup.BACKUP_PREFIX}20260901-080000.dump",
    ]
    assert len(backup.existing_backups(tmp_path)) == 2


def test_rotate_backups_rejects_zero_keep(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="keep debe ser positivo"):
        backup.rotate_backups(tmp_path, keep=0)


def test_create_database_backup_writes_and_rotates(tmp_path: Path) -> None:
    for day in range(1, 4):
        (tmp_path / f"{backup.BACKUP_PREFIX}2026090{day}-080000.dump").write_bytes(b"x")
    runner = _fake_runner(b"contenido" * 100)

    result = backup.create_database_backup(
        _URL,
        out_dir=tmp_path,
        keep=2,
        now=datetime(2026, 9, 8, 8, 0, tzinfo=UTC),
        runner=runner,
    )

    assert result.path.is_file()
    assert result.size_bytes == 900
    assert len(result.removed) == 2
    assert len(backup.existing_backups(tmp_path)) == 2
    # El backup recien creado sobrevive a la rotacion.
    assert result.path.name in {path.name for path in backup.existing_backups(tmp_path)}


def test_create_database_backup_passes_password_by_env(tmp_path: Path) -> None:
    runner = _fake_runner()

    backup.create_database_backup(_URL, out_dir=tmp_path, runner=runner)

    command, env = runner.calls[0]  # type: ignore[attr-defined]
    assert env["PGPASSWORD"] == "secreto"
    assert not any("secreto" in arg for arg in command)


def test_create_database_backup_creates_missing_directory(tmp_path: Path) -> None:
    target = tmp_path / "auto" / "anidado"

    result = backup.create_database_backup(_URL, out_dir=target, runner=_fake_runner())

    assert result.path.parent == target


def test_create_database_backup_fails_when_nothing_written(tmp_path: Path) -> None:
    def run(_command: Sequence[str], _env: Mapping[str, str]) -> None:
        return None

    with pytest.raises(BackupError, match="no genero"):
        backup.create_database_backup(_URL, out_dir=tmp_path, runner=run)


def test_create_database_backup_rejects_empty_dump(tmp_path: Path) -> None:
    runner = _fake_runner(b"")

    with pytest.raises(BackupError, match="archivo vacio"):
        backup.create_database_backup(_URL, out_dir=tmp_path, runner=runner)

    # Un dump vacio no debe quedar en disco fingiendo ser un respaldo valido.
    assert backup.existing_backups(tmp_path) == []


def test_default_backup_dir_points_at_repo_backups() -> None:
    directory = backup.default_backup_dir()

    assert directory.name == "auto"
    assert directory.parent.name == "postgres"
    assert directory.parent.parent.name == "backups"
