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

test:  ## Run unit tests
	$(COMPOSE) run --rm api pytest -q

lint:  ## Lint and format check
	$(COMPOSE) run --rm api ruff check .

shell-bash:  ## Open a shell in the API container
	$(COMPOSE) run --rm api bash

psql:  ## Open psql against the database
	$(COMPOSE) exec db psql -U prodex -d prodex