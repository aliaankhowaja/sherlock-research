# Research repo: experiments only. Every target works without make: bash scripts/<name>.sh
SHELL := bash
.DEFAULT_GOAL := help

.PHONY: help setup test eval g1-eval g1-public g1-api-smoke g1-pipeline g1-api-public score

help: ## Show this list
	@grep -hE '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

setup: ## Install python dependencies (python/sherlock + harness, uv sync)
	@bash scripts/setup.sh

test: ## Run the test suites and re-check the committed evaluation results against docs/eval
	@bash scripts/test.sh

eval: ## Regenerate the 3-gate evaluation tables in docs/eval (about 5 minutes)
	cd python/sherlock && uv run python eval/run_eval.py --out ../../docs/eval

g1-eval: ## G1 ordering evaluations (planted + generated cases; local laya inference)
	@bash scripts/g1-eval.sh

g1-public: ## G1 ordering on the public trace corpus (local laya inference, no key)
	@bash scripts/g1-public.sh

g1-api-smoke: ## Smoke-test the hosted G1 API scorer with the sample card (provider from .env)
	@bash scripts/g1-api-smoke.sh

g1-pipeline: ## E1/E2: full 4-gate pipeline on the planted cases, hosted-LLM G1, small+big cards
	@bash scripts/g1-pipeline.sh

g1-api-public: ## E1/E2 public leg: hosted-LLM G1 ordering on the public trace corpus
	@bash scripts/g1-api-public.sh

score: ## Scored tables 1-5 + tests (metrics spec §2-§8) from the committed artifacts (about 1 minute)
	cd python/sherlock && uv run python eval/score.py --out ../../docs/eval
