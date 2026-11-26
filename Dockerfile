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
COPY web/ ./
RUN npm run build

# wise-board, a separate proprietary binary under its own EULA: --build-arg WISE_BOARD=1 fetches the version pinned in
# wise-board.version and checks it against the digest pinned in wise-board.sha256; without it the server has no
# handwritten boards. There is no gh here, so provenance is not attested unless WISE_BOARD_ATTEST=require fails it.
FROM base AS wise-board
ARG WISE_BOARD=0
ARG WISE_BOARD_BASE_URL
ARG WISE_BOARD_ATTEST=auto
WORKDIR /src
COPY wise-board.version wise-board.sha256 ./
COPY scripts/fetch-wise-board.sh scripts/
RUN if [ "$WISE_BOARD" = 1 ]; then \
      scripts/fetch-wise-board.sh /opt/wise-board \
      && echo "This image contains wise-board, a separately licensed proprietary binary; its EULA is /opt/wise-board/EULA.md." > /opt/wise-board/NOTICE; \
    else mkdir -p /opt/wise-board; fi

FROM base AS app
# opencode: --build-arg AGENT_PACKAGES="@anthropic-ai/claude-code opencode-ai", about 830 MB more; none for the
# anthropic backend: --build-arg AGENT_PACKAGES=""
ARG AGENT_PACKAGES="@anthropic-ai/claude-code"
RUN if [ -n "$AGENT_PACKAGES" ]; then npm install -g --omit=dev $AGENT_PACKAGES && npm cache clean --force; fi
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY diagrams/package.json diagrams/package-lock.json diagrams/
RUN cd diagrams && npm ci --omit=dev && npm cache clean --force
COPY wise_scholar/ wise_scholar/
COPY diagrams/render.mjs diagrams/
COPY --from=web /src/web/dist web/dist
COPY --from=wise-board /opt/wise-board /opt/wise-board
ARG WISE_BOARD=0
LABEL io.wise-scholar.wise-board.included="$WISE_BOARD" \
      io.wise-scholar.wise-board.notice="1: contains the separately licensed proprietary wise-board binary, EULA at /opt/wise-board/EULA.md"
RUN mkdir data workspace && chown app:app data workspace
USER app
ENV PATH=/app/.venv/bin:/opt/wise-board:$PATH WISE_SCHOLAR_LISTEN=0.0.0.0 DISABLE_AUTOUPDATER=1
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
