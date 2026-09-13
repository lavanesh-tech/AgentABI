.PHONY: venv install fmt lint typecheck test run infra-up infra-down infra-logs

VENV := backend/.venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

venv:
	python3.12 -m venv $(VENV)

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -e "backend[dev]"

fmt:
	$(VENV)/bin/ruff format backend/app backend/tests
	$(VENV)/bin/ruff check --fix backend/app backend/tests

lint:
	$(VENV)/bin/ruff check backend/app backend/tests

typecheck:
	cd backend && ../$(VENV)/bin/mypy app

test:
	cd backend && ../$(VENV)/bin/pytest

run:
	cd backend && ../$(VENV)/bin/uvicorn app.main:app --reload

infra-up:
	docker compose up -d postgres redis neo4j kafka

infra-down:
	docker compose down

infra-logs:
	docker compose logs -f
