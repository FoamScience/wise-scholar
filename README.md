# Wise Scholar

A self-hosted AI tutor with a web interface. It interviews you, picks a teaching approach for the topic, and teaches through hints, exercises, confidence-rated quick checks and spaced reviews. The tutor runs through Claude Code or opencode on your own machine.

The research behind each teaching behaviour is listed in [docs/science.md](docs/science.md).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) with Python 3.11 or newer
- Node.js with npm
- One agent backend:
  - [Claude Code](https://claude.com/claude-code), logged in (`claude` on your `PATH`), or
  - [opencode](https://opencode.ai), with a provider configured (`opencode` on your `PATH`)

> [!NOTE]
> The tutor's file and shell tools currently run unsandboxed in `workspace/<course>/`.
> Run this only on a machine you trust it with.

## Run

```bash
make serve
```

This builds the web interface and serves everything at <http://127.0.0.1:8321>.

## Choose the backend and model

Set `WISE_SCHOLAR_AGENT` to `<backend>` or `<backend>/<model>`. The backend is `claude` or `opencode`.

```bash
make serve                                                              # Claude Code, its default model
WISE_SCHOLAR_AGENT=claude/sonnet make serve                             # Claude Code, a named model
WISE_SCHOLAR_AGENT=opencode make serve                                  # opencode, its default model
WISE_SCHOLAR_AGENT='opencode/openrouter/openrouter/free' make serve   # opencode, provider/model
```

The model must be able to call tools reliably.

## Develop

```bash
make build   # once, to install the web dependencies
make dev     # API with reload on :8321, web dev server on :5173
make test    # Python tests
```

## Where things live

- `data/` holds the database. Before a schema upgrade the file is copied to `data/wise-scholar.db.v<N>.bak`.
- `workspace/<course>/` holds each course's exercise files. Deleting a course removes its folder.
- `.mcp.json` and `opencode.json` declare the tutor's MCP server for this repository only.
