.PHONY: help up down test test-all test-pg lint migrate simulate clean release

help:
	@echo "Available commands:"
	@echo "  make up        - Start containers with docker-compose"
	@echo "  make down      - Stop all containers"
	@echo "  make test      - Run test suite with pytest"
	@echo "  make test-all  - Run test suite against all configured databases"
	@echo "  make test-pg   - Run test suite against PostgreSQL 16 test container"
	@echo "  make lint      - Run ruff linter"
	@echo "  make migrate   - Apply Alembic database migrations"
	@echo "  make simulate  - Run simulated full-day scenario"
	@echo "  make release   - Build release zip artifact"

up:
	docker compose up -d --build

down:
	docker compose down

test:
	python scripts/verify_review_tests.py
	python -m pytest tests/ -v
	python scripts/check_report.py

test-all: test

test-pg:
	docker compose -f docker-compose.test.yml up -d
	TEST_DATABASE_URL="postgresql+asyncpg://postgres_test:test_secret_password_for_pg16@localhost:5433/barbershop_test" REQUIRE_PG=1 python -m pytest tests/ -v
	docker compose -f docker-compose.test.yml down

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
