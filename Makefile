.DEFAULT_GOAL := help
.PHONY: help install demo brief console jarvis telemetry leads test lint fmt eval review check clean

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
	uv run python -m agents.prospecting.demo
	uv run python -m agents.outreach.demo
	uv run python -m agents.knowledge_base.demo
	uv run python -m agents.prompt_optimizer.demo
	uv run python -m agents.code_reviewer.demo
	uv run python -m agents.supervisor.demo
	uv run python -m agents.supervisor.campaign_demo
	uv run python -m console.demo
	uv run python -m console.chat_demo
	uv run python -m telemetry.demo
	uv run python -m jarvis.demo

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
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov traces briefs vault .cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

brief: ## Run every agent and write the morning brief to briefs/
	uv run python -m agents.supervisor.demo
	uv run python -m console.demo

console: ## Serve the operator console on http://127.0.0.1:8756
	uv run python -m console.server

jarvis: ## Serve the J.A.R.V.I.S. dashboard on http://127.0.0.1:8756
	uv run python -m jarvis

telemetry: ## Read this machine's own Claude Code history (no key, no network)
	uv run python -m telemetry.demo

eval: ## Run the deterministic eval suite
	uv run python -m evals

leads: ## Find businesses in an area (WHAT="Dachdecker" WHERE="München", add OUTREACH=1)
	uv run python -m agents.supervisor "$(WHAT)" "$(WHERE)" $(if $(OUTREACH),--outreach,) $(if $(SEND),--send,)

review: ## Review this repo and report a worklist (add APPLY=1 to write patches)
	uv run python -m agents.code_reviewer $(if $(APPLY),--apply,)
