# The server with its web app, diagram renderer and agent CLIs. Learner commands run in bubblewrap, which needs the
# container started with seccomp, AppArmor and systempaths unconfined (compose.yaml sets them).
FROM debian:trixie-slim AS base
RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap ca-certificates curl git iproute2 nodejs npm python3 tini \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_PYTHON=/usr/bin/python3 UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_NO_CACHE=1

FROM base AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY wise_scholar/kit/ /src/wise_scholar/kit/
COPY web/ ./
RUN npm run build

FROM base AS app
# opencode: --build-arg AGENT_PACKAGES="@anthropic-ai/claude-code opencode-ai", about 830 MB more
ARG AGENT_PACKAGES="@anthropic-ai/claude-code"
RUN npm install -g --omit=dev $AGENT_PACKAGES && npm cache clean --force
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY diagrams/package.json diagrams/package-lock.json diagrams/
RUN cd diagrams && npm ci --omit=dev && npm cache clean --force
COPY wise_scholar/ wise_scholar/
COPY diagrams/render.mjs diagrams/
COPY --from=web /src/web/dist web/dist
RUN mkdir data workspace && chown app:app data workspace
USER app
ENV PATH=/app/.venv/bin:$PATH WISE_SCHOLAR_LISTEN=0.0.0.0 DISABLE_AUTOUPDATER=1
VOLUME ["/app/data", "/app/workspace", "/home/app"]
EXPOSE 8321
HEALTHCHECK CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8321/', timeout=5)"
ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "wise_scholar.serve"]

FROM app AS test
USER root
RUN apt-get update && apt-get install -y --no-install-recommends procps && rm -rf /var/lib/apt/lists/*
RUN uv sync --frozen --no-dev --no-install-project --group test
COPY tests/ tests/
USER app
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_sandbox.py", "tests/test_serve.py"]
