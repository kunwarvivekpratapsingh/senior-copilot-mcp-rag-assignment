# Multi-MCP Enterprise Operations Copilot
#
# Canonical task runner, used by CI and inside containers.
# Windows users without `make`: tasks.ps1 exposes the same target names
#   .\tasks.ps1 lint    ==   make lint
.DEFAULT_GOAL := help

PY ?= python
PIP ?= $(PY) -m pip
COMPOSE ?= docker compose

.PHONY: help install lint format typecheck test test-unit test-integration test-e2e \
        contract coverage ingest smoke up down logs ps docs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- Setup -----------------------------------------------------------------

install: ## Install all components plus dev tooling, editable
	$(PIP) install -e ".[all]"

# --- Quality gates ---------------------------------------------------------

lint: ## Ruff check (includes flake8-bandit security rules)
	$(PY) -m ruff check .

format: ## Ruff format in place
	$(PY) -m ruff format .

typecheck: ## mypy static analysis
	$(PY) -m mypy .

# --- Tests -----------------------------------------------------------------

test: ## Run the whole suite (no running services required)
	$(PY) -m pytest

test-unit: ## Unit tests only
	$(PY) -m pytest tests/unit

test-integration: ## Integration tests (MCP client <-> servers)
	$(PY) -m pytest tests/integration

test-e2e: ## The acceptance scenario over the HTTP surface, in-process
	$(PY) -m pytest tests/e2e

coverage: ## Test suite with coverage report
	$(PY) -m pytest --cov --cov-report=term-missing --cov-report=html

# --- Contract check --------------------------------------------------------
# The Postman collections are the Alarm API specification. This target is the
# acceptance gate for the simulator: it must pass before the MCP server is
# considered integrable. Requires: npm i -g newman
POSTMAN_DIR ?= postman
contract: ## Run all Postman collections against a running simulator
	newman run $(POSTMAN_DIR)/Alarm-API-Simulator.postman_collection.json
	newman run $(POSTMAN_DIR)/scenarios/Alarm-API-Scenarios.postman_collection.json
	newman run $(POSTMAN_DIR)/chaining/Alarm-API-Chaining.postman_collection.json

# --- Application tasks -----------------------------------------------------

ingest: ## Build the RAG index from rag/documents
	$(PY) -m rag.ingestion.cli --docs ./rag/documents --reset

smoke: ## Chain two MCP tools without the GUI or an LLM
	$(PY) scripts/mcp_smoke.py

# --- Docker ----------------------------------------------------------------

up: ## Build and start the full stack
	$(COMPOSE) up --build -d

down: ## Stop the stack and remove volumes
	$(COMPOSE) down -v

logs: ## Tail logs from every service
	$(COMPOSE) logs -f

ps: ## Show service health
	$(COMPOSE) ps

# --- Documentation ---------------------------------------------------------
# Both generators must produce no git diff when re-run — that is the proof
# that the committed docs match the code.
docs: ## Regenerate the MCP tool catalog and export diagrams
	$(PY) scripts/gen_tool_catalog.py
	bash scripts/gen_diagrams.sh

clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml dist build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
