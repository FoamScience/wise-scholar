.PHONY: dev dev-server dev-web build serve test

dev:
	$(MAKE) -j2 dev-server dev-web

dev-server:
	uv run uvicorn wise_scholar.app:app --reload --reload-dir wise_scholar --port 8321

dev-web:
	cd web && npm run dev

build:
	cd web && npm install && npm run build

serve: build
	uv run uvicorn wise_scholar.app:app --port 8321

test:
	uv run pytest -q
