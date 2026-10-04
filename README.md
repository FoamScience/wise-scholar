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

Other settings, all optional:

| Variable | Meaning | Default |
|---|---|---|
| `WISE_SCHOLAR_PORT` | port of the app; the tutor's MCP connection follows it, so it must match the port the server is started on (`make serve` does that) | `8321` |
| `WISE_SCHOLAR_DB` | path of the database file | `data/wise-scholar.db` |
| `WISE_SCHOLAR_WORKSPACE` | root folder of the course workspaces | `workspace/` |
| `WISE_SCHOLAR_OPENCODE_PORT` | port of the opencode server the app starts | `8322` |

A second instance for testing, beside the real one:

```bash
WISE_SCHOLAR_PORT=8331 WISE_SCHOLAR_OPENCODE_PORT=8332 WISE_SCHOLAR_DB=/tmp/test.db WISE_SCHOLAR_WORKSPACE=/tmp/ws make serve
```

## Languages

The interface and the tutor work in English, French or Arabic. Pick the language at the top right, next to the profile name. It is stored with the profile, and the tutor writes in it from its next reply; lessons already written stay as they are. In a language course it is the language of instructions and explanations, not the one being learned.

A new language is one file: copy `web/src/locales/en.json`, translate it, and add its code to `web/src/locale.ts`, `web/src/i18n.ts` and the `Locale` names in `wise_scholar/app.py`. `make test` checks that every key and every learner-facing server error is covered.

## Speech (optional)

Off by default. Listen buttons use the browser's own voice and there is no microphone input until you install the speech extras:

```bash
make speech
```

This creates a separate environment under `speech/` (torch, Chatterbox Multilingual, faster-whisper, Piper, the MMS forced aligner) and downloads the models once, about 8 GB in total. Afterwards reading texts play with a local neural voice sentence by sentence, the chat gets a push-to-talk button, and language lessons get speaking tasks: read aloud, shadow a line, answer a spoken question. Recordings are scored word by word by forced alignment (the MMS aligner is licensed CC-BY-NC 4.0, fine for your own use) and kept under `data/audio/speaking/`. Chatterbox runs on the GPU; without one, Piper speaks on the CPU (German and English voices are installed). Nothing is downloaded while you learn; the worker starts on first use and stops after ten idle minutes.

### Casts (experimental)

With speech installed, `WISE_SCHOLAR_PODCASTS=1 make serve` lets the tutor turn a two-voice dialogue it writes into a 5 to 8 minute audio cast (`ffmpeg` must be on the path): a recap of the lesson, or a quiz-cast that pauses for a confidence-rated question every couple of minutes. The two voices are Chatterbox and Piper. Rendering runs in the background and takes about a minute per five minutes of audio on a GPU.

## Develop

```bash
make build   # once, to install the web dependencies
make dev     # API with reload on :8321, web dev server on :5173
make test    # Python and web tests
```

## Where things live

- `data/` holds the database, recordings and casts under `data/audio/`, and the files you add to a course under `data/sources/` (PDF, EPUB, HTML, Markdown, text, code; the tutor searches them and reads one section at a time). Before a schema upgrade the database is copied to `data/wise-scholar.db.v<N>.bak`.
- `workspace/<course>/` holds each course's exercise files. Deleting a course removes its folder.
- `.mcp.json` and `opencode.json` declare the tutor's MCP server for this repository only.
