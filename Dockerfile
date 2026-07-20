FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY reasons_service/ reasons_service/

RUN pip install --no-cache-dir .

RUN useradd --create-home --shell /bin/bash appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "reasons_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
