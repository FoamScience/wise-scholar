.PHONY: help dev dev-server dev-web build serve test speech pdf art search
.DEFAULT_GOAL := help

# this machine's own settings (`export NAME=value` lines), kept out of git
-include .env

WISE_SCHOLAR_PORT ?= 8321
export WISE_SCHOLAR_PORT

help: ## list the targets
	@grep -hE '^[A-Za-z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{ printf "  %-12s %s\n", $$1, $$2 }'

dev: ## API with reload on :8321 and the web dev server on :5173
	$(MAKE) -j2 dev-server dev-web

dev-server: ## API alone, with reload
	uv run uvicorn wise_scholar.app:app --reload --reload-dir wise_scholar --port $(WISE_SCHOLAR_PORT)

dev-web: ## web dev server alone
	cd web && npm run dev

web/node_modules: web/package-lock.json
	cd web && npm install

diagrams/node_modules: diagrams/package-lock.json
	cd diagrams && npm install

build: web/node_modules diagrams/node_modules ## web and diagram dependencies, web/dist; a running server serves it at once
	cd web && npm run build

serve: build ## build, then serve on WISE_SCHOLAR_PORT (8321 unless set), WISE_SCHOLAR_LISTEN adds addresses
	uv run python -m wise_scholar.serve

test: web/node_modules ## Python and web tests
	uv run pytest -q
	cd web && npm test

speech: ## opt-in: torch, Chatterbox, whisper, Piper and models, about 7 GB
	cd speech && uv sync && uv run --no-sync python worker.py --download

art: ## opt-in: Bioicons art pack, 231 MB download, 110 MB in data/art/
	uv run --no-sync python -m wise_scholar.art fetch bioicons

pdf: ## opt-in: Playwright and headless Chromium, 110 MB, for PDF export
	uv sync --inexact --extra pdf && uv run --no-sync playwright install --only-shell chromium

search: ## opt-in: model2vec and its multilingual model, 512 MB, for search by meaning; without it search goes by words
	uv sync --inexact --extra search && uv run --no-sync python -m wise_scholar.search
