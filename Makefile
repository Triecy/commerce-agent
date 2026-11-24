# Commerce Agent developer commands. Run `make help` for the list.
SHELL := /bin/bash
.DEFAULT_GOAL := help

UV      ?= uv
COMPOSE := docker compose -f deploy/compose.yml --env-file .env --profile core

.PHONY: help install up down ps logs stack-check test lint typecheck fmt check require-docker

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

lint: ## Ruff lint + format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

typecheck: ## mypy (strict for commerce_agent.common)
	$(UV) run mypy

fmt: ## Auto-format and apply safe lint fixes
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

check: lint typecheck test ## Everything CI runs
