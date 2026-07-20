FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md hatch_build.py ./
RUN pip install --no-cache-dir .

COPY reasons_service/ reasons_service/
COPY alembic.ini ./
COPY alembic/ alembic/

RUN useradd --create-home --shell /bin/bash appuser
USER appuser

ENV PORT=8000
EXPOSE ${PORT}

CMD ["sh", "-c", "uvicorn reasons_service.app:app --host 0.0.0.0 --port ${PORT}"]
