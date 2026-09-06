FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:${PATH}"

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY src ./src

RUN uv sync --no-dev --extra ml

EXPOSE 8000

CMD ["uvicorn", "futpredict.main:app", "--host", "0.0.0.0", "--port", "8000"]
