.PHONY: help dev dev-server dev-web build serve test speech pdf art
.DEFAULT_GOAL := help

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

build: web/node_modules ## web dependencies and web/dist; a running server serves it at once
	cd web && npm run build

serve: build ## build, then serve on :8321 (WISE_SCHOLAR_PORT changes it)
	uv run uvicorn wise_scholar.app:app --port $(WISE_SCHOLAR_PORT)

test: web/node_modules ## Python and web tests
	uv run pytest -q
	cd web && npm test

speech: ## opt-in: torch, Chatterbox, whisper, Piper and models, about 7 GB
	cd speech && uv sync && uv run --no-sync python worker.py --download

art: ## opt-in: Bioicons art pack, 231 MB download, 110 MB in data/art/
	uv run --no-sync python -m wise_scholar.art fetch bioicons

pdf: ## opt-in: Playwright and headless Chromium, 110 MB, for PDF export
	uv sync --inexact --extra pdf && uv run --no-sync playwright install --only-shell chromium
