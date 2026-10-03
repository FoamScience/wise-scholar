.PHONY: dev dev-server dev-web build serve test

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
