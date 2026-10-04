.PHONY: dev dev-server dev-web build serve test speech pdf

WISE_SCHOLAR_PORT ?= 8321
export WISE_SCHOLAR_PORT

dev:
	$(MAKE) -j2 dev-server dev-web

dev-server:
	uv run uvicorn wise_scholar.app:app --reload --reload-dir wise_scholar --port $(WISE_SCHOLAR_PORT)

dev-web:
	cd web && npm run dev

web/node_modules: web/package-lock.json
	cd web && npm install

build: web/node_modules
	cd web && npm run build

serve: build
	uv run uvicorn wise_scholar.app:app --port $(WISE_SCHOLAR_PORT)

test: web/node_modules
	uv run pytest -q
	cd web && npm test

# Opt-in: installs the speech environment (torch, Chatterbox, whisper, Piper) and downloads the models, about 7 GB.
speech:
	cd speech && uv sync && uv run --no-sync python worker.py --download

# Opt-in: installs Playwright and its headless Chromium, about 110 MB, for exporting a course as a PDF.
pdf:
	uv sync --inexact --extra pdf && uv run --no-sync playwright install --only-shell chromium
