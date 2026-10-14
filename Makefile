COMPOSE ?= docker compose
API     := $(COMPOSE) run --rm --no-deps api

.DEFAULT_GOAL := help

.PHONY: help up down logs ingest eval test lint psql shell-bash build

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-10s %s\n", $$1, $$2}'

build:  ## Build the API image
	$(COMPOSE) build api

up:  ## Start everything (db, ollama, api, model pull)
	$(COMPOSE) up -d
	@echo "Health check: curl http://localhost:8000/health"

down:  ## Stop everything
	$(COMPOSE) down

logs:  ## Tail API logs
	$(COMPOSE) logs -f api

ingest:  ## Run a full ingestion
	$(COMPOSE) run --rm api python -m app.ingestion.pipeline

ingest-repo:  ## Ingest one repo: make ingest-repo REPO=acme/prodex-core
	$(COMPOSE) run --rm api python -m app.ingestion.pipeline --repo "$(REPO)"

eval:  ## Run the evaluation harness
	$(COMPOSE) run --rm api python eval/run_eval.py

# The runtime image ships without dev dependencies, so test and lint install them
# into the container's virtualenv on the fly. The production image stays lean.
test:  ## Run unit tests
	$(COMPOSE) run --rm api uv run --frozen --group dev pytest -q

lint:  ## Lint
	$(COMPOSE) run --rm api uv run --frozen --group dev ruff check .

shell-bash:  ## Open a shell in the API container
	$(COMPOSE) run --rm api bash

psql:  ## Open psql against the database
	$(COMPOSE) exec db psql -U prodex -d prodex