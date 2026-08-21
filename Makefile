.DEFAULT_GOAL := help
.PHONY: help install demo brief overlay test lint fmt eval check clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies (including dev extras)
	uv sync --all-extras

demo: ## Run every demo — all work with no API key and no network
	uv run python -m core.demo
	uv run python -m agents.email_triage.demo
	uv run python -m agents.calendar_booking.demo
	uv run python -m agents.call_intake.demo
	uv run python -m agents.lead_research.demo
	uv run python -m agents.knowledge_base.demo
	uv run python -m agents.brain.demo
	uv run python -m console.demo

test: ## Run the test suite with coverage
	uv run pytest --cov=core --cov-report=term-missing

lint: ## Check formatting and lint rules
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Auto-fix formatting and lint rules
	uv run ruff format .
	uv run ruff check --fix .

check: lint test eval demo ## Everything CI runs, in the same order

clean: ## Remove caches and local run artifacts
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov traces briefs vault
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

brief: ## Run every agent and write the morning brief to briefs/
	uv run python -m agents.brain.demo
	uv run python -m console.demo

overlay: ## Serve the live overlay on http://127.0.0.1:8787
	uv run python -m console.server

eval: ## Run the deterministic eval suite
	uv run python -m evals
