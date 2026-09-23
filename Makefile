.PHONY: dev test lint lint-fix check build migrate migrate-down docker-up docker-down docker-build clean

dev:
	uv run uvicorn reasons_service.app:app --reload --host 0.0.0.0 --port 8000

test:
	uv run pytest tests/

lint:
	uv run ruff check reasons_service/ tests/

lint-fix:
	uv run ruff check --fix reasons_service/ tests/
	uv run ruff format reasons_service/ tests/

check: lint test

build:
	uv build

migrate:
	uv run alembic upgrade head

migrate-down:
	uv run alembic downgrade -1

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-build:
	docker compose build

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	rm -rf dist/
