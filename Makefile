.PHONY: help up down test lint migrate simulate clean

help:
	@echo "Available commands:"
	@echo "  make up        - Start containers with docker-compose"
	@echo "  make down      - Stop all containers"
	@echo "  make test      - Run test suite with pytest"
	@echo "  make lint      - Run ruff linter"
	@echo "  make migrate   - Apply Alembic database migrations"
	@echo "  make simulate  - Run simulated full-day scenario"

up:
	docker compose up -d --build

down:
	docker compose down

test:
	python -m pytest tests/ -v

lint:
	python -m ruff check .

migrate:
	python -m alembic upgrade head

simulate:
	python scripts/simulate_day.py

clean:
	rm -rf __pycache__ .pytest_cache .ruff_cache *.db dist/

release:
	python scripts/build_release.py
