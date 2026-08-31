# Backups PostgreSQL

Esta carpeta contiene backups versionados de la base principal del proyecto.
No esta ignorada por Git a proposito, para que otra computadora pueda clonar el
repositorio y restaurar el estado de trabajo.

## Backup actual

- Archivo: `futbol_predict_2026-08-27.dump`
- Formato: `pg_dump -Fc`
- Base: `futbol_predict`
- PostgreSQL origen: 18.6
- Fecha de creacion: 2026-08-27
- Tamano aproximado: 3.7 MB
- SHA256:
  `0EB0F02E67CDCA03A5BA9089F0D20EE73823B466B06B0B249F8CAE7768727D71`

Conteos principales al momento del backup:

```text
calibration_bins 2048
elo_ratings      35874
features         17937
leagues          5
matches          17941
model_metrics    175
model_versions   175
odds             17941
predictions      62295
teams            161
```

## Restaurar desde Docker Compose

Desde la raiz del repo:

```powershell
cd E:\Trabajos\Propios\futbol-predict
docker compose up -d postgres
docker cp backups\postgres\futbol_predict_2026-08-27.dump futbol_predict_postgres:/tmp/futbol_predict_2026-08-27.dump
docker compose exec postgres pg_restore -U futbol -d futbol_predict --clean --if-exists --no-owner --no-privileges /tmp/futbol_predict_2026-08-27.dump
```

Despues de restaurar:

```powershell
docker compose up -d api frontend mlflow
docker compose exec api python -m futpredict.cli db-status
docker compose exec api python -m futpredict.cli model-metrics-status
docker compose exec api python -m futpredict.cli predictions-status
docker compose exec api python -m futpredict.cli calibration-status --bins 10
```

Si MLflow esta vacio en la otra computadora, se puede reconstruir desde
PostgreSQL:

```powershell
docker compose exec api python -m futpredict.cli sync-mlflow-model-versions --force
```
