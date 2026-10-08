# Wise Scholar

A self-hosted AI tutor with a web interface. It interviews you, picks a teaching approach for the topic, and teaches through hints, exercises, confidence-rated quick checks and spaced reviews. The tutor runs through Claude Code or opencode on your own machine.

The research behind each teaching behaviour is listed in [docs/science.md](docs/science.md).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) with Python 3.11 or newer
- Node.js with npm
- One agent backend:
  - [Claude Code](https://claude.com/claude-code), logged in (`claude` on your `PATH`), or
  - [opencode](https://opencode.ai), with a provider configured (`opencode` on your `PATH`)
- [bubblewrap](https://github.com/containers/bubblewrap) (`bwrap`, Linux), for the sandbox that commands run in

> [!NOTE]
> In hands-on lessons the tutor writes exercise files in `workspace/<course>/` and runs commands there, and so does the Run button.
> Every such command runs inside bubblewrap. It sees the system's programs (`/usr`, `/etc`, `/opt`), the toolchain folders your `PATH`
> points into under your home directory (`~/.cargo`, `~/.nvm`, `~/go`, `~/.local/bin`, ...), and its own course workspace, which is the
> only place it can write. It has no network and no access to the machine's sockets (Docker, D-Bus), sees nothing else of your home
> directory, the database or other courses, and stops after 30 seconds. Where a user systemd runs it gets 2 GB of memory and
> 256 tasks; elsewhere those two limits are missing and the server says so at start. Two commands run at a time.
> Inside, the user is `learner` with the home directory `/home/learner`, and the course sits at
> `/home/learner/wise-scholar/workspace/<course>`: paths, tracebacks, `whoami` and the environment name no real user or folder, and
> the exercise card names files the same way. A command can still read the real folders behind the mounts in `/proc/self/mountinfo`.
> Without the sandbox (`WISE_SCHOLAR_SANDBOX=0`) commands see and print the real paths.
> A course has a disk limit of 4 GB for its workspace, and as much again for its command cache. No single file can pass it, and the
> server looks about twice a second while a command runs: a command found pushing its course past the limit is stopped, and a cache
> past it is emptied. That is a watch, not a filesystem quota: a fast disk takes what is written between two looks, and a file
> deleted while still open is not seen until the command ends. Not covered either: a token you keep inside one of those toolchain
> folders is readable to commands. The agent itself has no shell or file tools; it acts only through the server.
> For an instance other people use, switch commands off (`WISE_SCHOLAR_COMMANDS=0`).
>
> A command reaches the internet only when the learner allows it. The tutor asks on a card that shows the command and its reason
> ("Allow once" or "Don't allow"). An allowed command runs once, for up to two minutes, still without a network of its own: it gets
> an HTTP proxy that the server runs for it, and that proxy connects only to ports 80 and 443 of public IPv4 addresses: not to
> this machine, private ranges, the networks this machine is attached to, or anything over IPv6. Package indexes, git over https
> and downloads work. No other command of that course runs meanwhile and the tutor cannot change its files; the Run button of an
> exercise is always offline. What it does not stop: an allowed command can send what it can read (the workspace, the toolchain
> folders) to any public site; and it can reach whatever answers on a public address, which includes your router's outer address
> and anything you expose through it. Read the command before you allow it.

## Run

```bash
make serve
```

This builds the web interface and serves everything at <http://127.0.0.1:8321>.

A new course opens on its interview page. Before the first question you can say more about what the course should cover (for example "science class, second year of high school") and how many hours of teaching the whole course should take. Both are optional: the tutor keeps the course inside that scope and sizes the course map so its sittings add up to the time.

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
| `WISE_SCHOLAR_COMMANDS` | `0` serves without command execution: the tutor gets no workspace tools and poses no runnable exercises, and Run is refused. For instances opened to other people | `1` |
| `WISE_SCHOLAR_VAULT` | an Obsidian vault folder on this machine (or one synced to it): the server keeps `Wise Scholar/<course>/` inside it current: a few seconds after a course changes its notes are rewritten (an edit you made to one of them is lost; keep your own writing in files of your own, which are never touched) and notes it wrote that the course no longer has, or a folder left by a renamed course, are removed. Plots stay as specs in the synced notes | unset |
| `WISE_SCHOLAR_KEEP_DAYS` | a course untouched for this many days has its files cleaned up: workspace, command cache and agent sessions go, the record stays and each exercise keeps a text copy of its files; checked at start and every 6 hours; `uv run python -m wise_scholar.cleanup` lists what would go and `--delete` removes it, with the server stopped | `90` |
| `WISE_SCHOLAR_WORKSPACE_MB` | what one course may hold on disk, in its workspace and again in its command cache. Watched while a command runs, not a filesystem quota; with the sandbox off only the workspace is watched | `4096` |
| `WISE_SCHOLAR_SANDBOX` | `0` runs commands without bubblewrap (macOS, containers that forbid it): as the server's user, with network, the whole home directory including the agent's login, no memory or task limits, and processes that can outlive the time limit. Only for a machine and a tutor model you trust fully | `1` |
| `WISE_SCHOLAR_SANDBOX_PATHS` | extra folders commands may read, separated by `:`, for toolchains that `PATH` does not point into. Everything in them becomes readable to commands; the home directory and folders holding the database or the courses are ignored | none |

A second instance for testing, beside the real one:

```bash
WISE_SCHOLAR_PORT=8331 WISE_SCHOLAR_OPENCODE_PORT=8332 WISE_SCHOLAR_DB=/tmp/test.db WISE_SCHOLAR_WORKSPACE=/tmp/ws make serve
```

## Languages

The interface and the tutor work in English, French or Arabic. Pick the language at the top right, next to the profile name. It is stored with the profile, and the tutor writes in it from its next reply; lessons already written stay as they are. In a language course it is the language of instructions and explanations, not the one being learned. Arabic lays the page out right to left; code, math and diagrams stay left to right, and each lesson block follows the direction of its own text.

A new language is one file: copy `web/src/locales/en.json`, translate it, and add its code to `web/src/locale.ts`, `web/src/i18n.ts` and the `Locale` names in `wise_scholar/app.py`. `make test` checks that every key and every learner-facing server error is covered.

## Export a course as a PDF (optional)

"Export as a book" on the course map opens the whole course as a book: cover, contents, the interview and the placement check, one chapter per lesson with the tutor conversation, your projects and the course's error notebook. It keeps the theme you are using and the site's typefaces.

```bash
make pdf
```

installs Playwright and a headless Chromium, about 110 MB, and the book page gets a "Download PDF" button: the server prints that page itself. An installed Google Chrome is used when the Chromium download is skipped. Without `make pdf` the button opens the browser's print dialog instead; choose "Save as PDF" there.

The downloaded file is encrypted (AES-256) and opens without a password; readers that honour PDF permissions then allow printing only: no copying, text extraction, editing or annotation. That lock is advisory. A tool that ignores the permission bits still reads the text, so it keeps honest readers out, not determined ones. The browser's own "Save as PDF" is not locked.

"Export for Obsidian", beside it, downloads the course as a folder of Markdown notes to drop into any [Obsidian](https://obsidian.md) vault: one note per unit, lesson, card, mistake, project and (in a language course) word, linked with wikilinks and carrying properties, with the course map as a canvas, the unit's review cards in the Spaced Repetition plugin's format, figures as SVG and plots as PNG when `make pdf` was run. Notes are named by id and title, so a later export overwrites them (a renamed unit leaves its old note behind) and leaves your own notes alone; keep your writing in notes of your own that link to these. It is plain text: no lock. With `WISE_SCHOLAR_VAULT` set, the server writes the same notes straight into your vault and keeps them current, so the download is only needed elsewhere.

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
