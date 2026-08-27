# Backend

Backend FastAPI y libreria principal del proyecto.

## Comandos utiles

```powershell
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy src
uv run uvicorn futpredict.main:app --reload
uv run python -m futpredict.cli club-elo-coverage-db --start-season 1617 --end-season 2526 --offline
uv run python -m futpredict.cli walk-forward-db --start-season 1617 --end-season 2526 --include-club-elo --dry-run
uv run python -m futpredict.cli freeze-walk-forward-predictions-db --start-season 1617 --end-season 2526 --dry-run
uv run python -m futpredict.cli evaluate-predictions-db --dry-run
uv run python -m futpredict.cli predictions-status
uv run python -m futpredict.cli export-openapi --output ../frontend/src/api/openapi.json
```

## Migraciones

```powershell
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "mensaje"
```
