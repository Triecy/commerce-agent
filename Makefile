# Commerce Agent developer commands. Run `make help` for the list.
SHELL := /bin/bash
.DEFAULT_GOAL := help

UV      ?= uv
COMPOSE := docker compose -f deploy/compose.yml --env-file .env --profile core

.PHONY: help install up down ps logs stack-check test lint typecheck fmt audit profile-categories test-integration migrate data data-reset check require-docker

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

install: ## Create .venv from uv.lock (exact pinned versions)
	$(UV) sync --locked

.env:
	@echo "No .env found; creating it from .env.example (local dev defaults)."
	cp .env.example .env

require-docker:
	@command -v docker >/dev/null 2>&1 || { echo "Docker is not installed. See README.md (Prerequisites)."; exit 1; }

up: require-docker .env ## Start Postgres (pgvector) + Redis and wait until both are healthy
	$(COMPOSE) up -d --wait --wait-timeout 120
	@bash deploy/scripts/stack-check.sh "$(COMPOSE)"

down: require-docker .env ## Stop the stack (named volumes are kept)
	$(COMPOSE) down

ps: require-docker .env ## Show service status
	$(COMPOSE) ps

logs: require-docker .env ## Tail service logs
	$(COMPOSE) logs -f --tail=100

stack-check: require-docker .env ## Verify pgvector is installed and Redis answers
	@bash deploy/scripts/stack-check.sh "$(COMPOSE)"

test: ## Run unit tests (offline, no API keys)
	$(UV) run pytest tests/unit

# testcontainers needs the Docker socket of the active context (Colima on the owner's Mac).
DOCKER_HOST ?= $(shell docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null)

test-integration: require-docker ## Integration tests against real containers (testcontainers)
	DOCKER_HOST=$(DOCKER_HOST) TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock \
		$(UV) run pytest tests/integration -m integration

lint: ## Ruff lint + format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

typecheck: ## mypy (strict for commerce_agent.common)
	$(UV) run mypy

fmt: ## Auto-format and apply safe lint fixes
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

migrate: .env ## Apply database migrations (alembic upgrade head); needs `make up`
	$(UV) run alembic upgrade head

data: migrate ## P1: download (pinned), split, simulate inventory, load Postgres; idempotent
	$(UV) run python -m commerce_agent.data.pipeline

data-reset: .env ## Drop all P1 tables and rebuild them from scratch (destroys loaded data)
	$(UV) run alembic downgrade base
	$(MAKE) data

profile-categories: ## P1: profile candidate Amazon categories (downloads ~570 MB to data/raw)
	$(UV) run python -m commerce_agent.data.profile --with-meta --out docs/results/p1-category-profiling.json

PIP_AUDIT_VERSION ?= 2.10.1
AUDIT_REQ := .audit-requirements.txt

audit: ## Scan locked dependencies for known vulnerabilities (pip-audit, NFR-5)
	$(UV) export --frozen --format requirements-txt --no-emit-project --quiet -o $(AUDIT_REQ)
	$(UV)x --from pip-audit==$(PIP_AUDIT_VERSION) pip-audit -r $(AUDIT_REQ) \
		--disable-pip --require-hashes --progress-spinner off; \
		status=$$?; rm -f $(AUDIT_REQ); exit $$status

check: lint typecheck test ## Everything CI runs (blocking); `make audit` runs separately
