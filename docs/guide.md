# Wise Scholar guide

Everything the [README](../README.md) leaves out: prerequisites, backends, options and where things live.

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

Other settings, all optional. To keep this machine's own values, put them in `.env` at the repository root, which git ignores and `make` reads as a makefile fragment: one `export NAME ?= value` line each, with no quotes (they would become part of the value). A value set in the shell when running `make` wins over the file.

| Variable | Meaning | Default |
|---|---|---|
| `WISE_SCHOLAR_PORT` | port of the app; the tutor's MCP connection follows it, so it must match the port the server is started on (`make serve` does that) | `8321` |
| `WISE_SCHOLAR_DB` | path of the database file | `data/wise-scholar.db` |
| `WISE_SCHOLAR_WORKSPACE` | root folder of the course workspaces | `workspace/` |
| `WISE_SCHOLAR_OPENCODE_PORT` | port of the opencode server the app starts | `8322` |
| `WISE_SCHOLAR_COMMANDS` | `0` serves without command execution: the tutor gets no workspace tools and poses no runnable exercises, and Run is refused. For instances opened to other people | `1` |
| `WISE_SCHOLAR_VAULT` | an Obsidian vault folder on this machine (or one synced to it): the server keeps `Wise Scholar/<course>/` inside it current: a few seconds after a course changes its notes are rewritten (an edit you made to one of them is lost; keep your own writing in files of your own, which are never touched) and notes it wrote that the course no longer has, or a folder left by a renamed course, are removed. Plots stay as specs in the synced notes | unset |
| `WISE_SCHOLAR_HOSTS` | host names the server answers to, comma-separated, ports ignored | `127.0.0.1,localhost,::1` |
| `WISE_SCHOLAR_LISTEN` | extra addresses `make serve` listens on, comma-separated, beside `127.0.0.1` (which the agents call back on): a tailnet address lets a proxy reach the server without opening it to the LAN; add the proxied name to `WISE_SCHOLAR_HOSTS` too. An address that cannot be bound is skipped with a warning. | unset |
| `WISE_SCHOLAR_MCP_SECRET` | the bearer token on `/mcp`; a fresh one per start when unset | unset |
| `WISE_SCHOLAR_AGENT_ENV` | extra environment variables the agent processes get, names or prefixes ending in `*`, comma-separated | unset |
| `WISE_SCHOLAR_TURNS` | tutor turns running at once | `2` |
| `WISE_SCHOLAR_TURNS_PER_HOUR` | tutor turns that may start in an hour | `200` |
| `WISE_SCHOLAR_TOOL_CALLS` | tool calls one turn may make | `80` |
| `WISE_SCHOLAR_MCP_CALLS` | tool calls a minute, all turns together | `600` |
| `WISE_SCHOLAR_KEEP_DAYS` | set it to clean up the files of courses untouched for that many days: workspace, command cache and agent sessions go, the record stays and each exercise keeps a text copy of its files; checked at start and every 6 hours. Unset, nothing is ever removed on its own. `uv run python -m wise_scholar.cleanup --days N` lists what would go and `--delete` removes it, with the server stopped | unset |
| `WISE_SCHOLAR_WORKSPACE_MB` | what one course may hold on disk, in its workspace and again in its command cache. Watched while a command runs, not a filesystem quota; with the sandbox off only the workspace is watched | `4096` |
| `WISE_SCHOLAR_SANDBOX` | `0` runs commands without bubblewrap (macOS, containers that forbid it): as the server's user, with network, the whole home directory including the agent's login, no memory or task limits, and processes that can outlive the time limit. Only for a machine and a tutor model you trust fully | `1` |
| `WISE_SCHOLAR_SANDBOX_PATHS` | extra folders commands may read, separated by `:`, for toolchains that `PATH` does not point into. Everything in them becomes readable to commands; the home directory and folders holding the database or the courses are ignored | none |

A second instance for testing, beside the real one:

```bash
WISE_SCHOLAR_PORT=8331 WISE_SCHOLAR_OPENCODE_PORT=8332 WISE_SCHOLAR_DB=/tmp/test.db WISE_SCHOLAR_WORKSPACE=/tmp/ws make serve
```

## Languages

The interface and the tutor work in English, French or Arabic. Pick the language at the top right, next to the profile name. It is stored with the profile, and the tutor writes in it from its next reply; lessons already written stay as they are. In a language course it is the language of instructions and explanations, not the one being learned. A quick check written in the language being learned carries a translation into it, folded under the question, in the lesson, in reviews and in the book. Arabic lays the page out right to left; code, math and diagrams stay left to right, and each lesson block follows the direction of its own text.

A new language is one file: copy `web/src/locales/en.json`, translate it, and add its code to `web/src/locale.ts`, `web/src/i18n.ts` and the `Locale` names in `wise_scholar/app.py`. `make test` checks that every key and every learner-facing server error is covered.

## Export a course as a PDF (optional)

"Export as a book" on the course map opens the whole course as a book: cover, contents, the interview and the placement check, one chapter per lesson with the tutor conversation, your projects and the course's error notebook. It keeps the theme you are using and the site's typefaces.

```bash
make pdf
```

installs Playwright and a headless Chromium, about 110 MB, and the book page gets a "Download PDF" button: the server prints that page itself. An installed Google Chrome is used when the Chromium download is skipped. Without `make pdf` the button opens the browser's print dialog instead; choose "Save as PDF" there.

The downloaded file is encrypted (AES-256) and opens without a password; readers that honour PDF permissions then allow printing only: no copying, text extraction, editing or annotation. That lock is advisory. A tool that ignores the permission bits still reads the text, so it keeps honest readers out, not determined ones. The browser's own "Save as PDF" is not locked.

Under the topic on the start page you can hand the course its materials before the interview: files, or the address of a PDF, EPUB or web page that the server fetches (public web addresses on ports 80 and 443, connecting to the address it checked; 50 MB at most). The router's outer address is the one public address it cannot tell apart. They land in the course's sources, the interview plans around them and lessons read them a section at a time.

"Export for Obsidian", beside it, downloads the course as a folder of Markdown notes to drop into any [Obsidian](https://obsidian.md) vault: one note per unit, lesson, card, mistake, project and (in a language course) word, linked with wikilinks and carrying properties, with the course map as a canvas, the unit's review cards in the Spaced Repetition plugin's format, figures as SVG and plots as PNG when `make pdf` was run. Notes are named by id and title, so a later export overwrites them (a renamed unit leaves its old note behind) and leaves your own notes alone; keep your writing in notes of your own that link to these. It is plain text: no lock. With `WISE_SCHOLAR_VAULT` set, the server writes the same notes straight into your vault and keeps them current, so the download is only needed elsewhere.

## Speech (optional)

Off by default. Listen buttons use the browser's own voice and there is no microphone input until you install the speech extras:

```bash
make speech
```

This creates a separate environment under `speech/` (torch, Chatterbox Multilingual, faster-whisper, Piper, the MMS forced aligner) and downloads the models once, about 8 GB in total. Afterwards reading texts play with a local neural voice sentence by sentence, the chat gets a push-to-talk button, and language lessons get speaking tasks: read aloud, shadow a line, answer a spoken question. Recordings are scored word by word by forced alignment (the MMS aligner is licensed CC-BY-NC 4.0, fine for your own use) and kept under `data/audio/speaking/`. Chatterbox runs on the GPU; without one, Piper speaks on the CPU (German and English voices are installed). Nothing is downloaded while you learn; the worker starts on first use and stops after ten idle minutes.

### Casts (experimental)

With speech installed, `WISE_SCHOLAR_PODCASTS=1 make serve` lets the tutor turn a two-voice dialogue it writes into a 5 to 8 minute audio cast (`ffmpeg` must be on the path): a recap of the lesson, or a quiz-cast that pauses for a confidence-rated question every couple of minutes. The two voices are Chatterbox and Piper. Rendering runs in the background and takes about a minute per five minutes of audio on a GPU.

## Art packs (optional)

The tutor draws its figures as SVG. With an art pack installed it composes them from professional illustrations instead of drawing a cell or a flask from scratch: it searches the pack, places the icons and adds its own labels and arrows. Each figure then carries the credit the icons' licences ask for, in the app, the book, the hand-outs and the Obsidian notes.

```bash
make art
```

downloads [Bioicons](https://bioicons.com), 231 MB, and keeps about 2,300 of its icons under `data/art/`, 110 MB: human physiology, animals, cells and their parts, blood and immunology, microbiology, viruses, lab apparatus, chemistry, nucleic acids, plants. The sets drawn by Servier (CC BY 3.0) and DBCLS (CC BY 4.0) are the bulk of it; the rest is CC0, MIT or BSD. Icons under a share-alike licence, icons over 400 KB and icons that need scripts, raster images or styles the figure allowlist refuses are left out at install. Nothing is fetched while you learn; the tutor sees the pack on its next turn, no restart needed. A lesson drawn before the pack was installed gets "Redraw the figures with the art pack" under its title: one tutor turn draws each figure again in its place, and each figure keeps the drawing it replaced, one step back, until the next redraw. `uv run python -m wise_scholar.art list` shows what is installed.

## Diagrams the server lays out

For subjects with a domain under `wise_scholar/penrose/` (cells in division, to start), the tutor does not draw: it states what is in the picture in [Penrose](https://penrose.cs.cmu.edu)'s Substance language (a cell at metaphase I, four chromosomes, which pairs are homologous) and the server lays the diagram out by the domain's rules, written and tested once per domain. A diagram that cannot satisfy its rules is refused with the rules named, so the tutor restates it rather than showing a wrong picture. `make build` installs the renderer (Node, under `diagrams/`); without it the tutor draws figures itself. These diagrams keep their plain stroke under the hand-drawn look.

## What keeps the tutor in its lane

- The tutor's tools answer only the agent processes this server starts: a secret made at start travels as a bearer token on `/mcp`, and each turn carries its own token, so a tool call may touch only the lesson and course of the turn it belongs to (with opencode, whose tools share one connection, any lesson whose turn is running). A turn gets at most 80 tool calls (`WISE_SCHOLAR_TOOL_CALLS`), the server at most 600 a minute (`WISE_SCHOLAR_MCP_CALLS`). To call the tools from a Claude Code session in this repository, set `WISE_SCHOLAR_MCP_SECRET` to a value of your own before starting the server and the session; `.mcp.json` reads it.
- Agent processes get a minimal environment: the basics, their own settings and the keys of model providers, plus whatever `WISE_SCHOLAR_AGENT_ENV` names (comma-separated names or prefixes ending in `*`). They run from `data/agents/`, never from a course workspace, and `opencode serve` takes a password only this process knows.
- Two tutor turns run at a time (`WISE_SCHOLAR_TURNS`) and at most 200 start in an hour (`WISE_SCHOLAR_TURNS_PER_HOUR`); the rest wait. The server answers only to the names in `WISE_SCHOLAR_HOSTS` (`127.0.0.1`, `localhost` and `::1` by default): set it to your domain behind a proxy, and a page on another name that resolves to this machine gets nothing.
- Everything the learner typed or uploaded reaches the tutor marked as text: a line of it that starts like an app line is escaped, facts are one sentence under 300 characters.
- A page from another site cannot change anything here: state-changing requests must come from this site's own pages.
- Uploaded documents are read in a child process with a time limit (2 minutes), a memory limit (2 GB), at most 2,000 pages and 20 million characters per file; a course holds at most 20 files and 200 MB.

## Develop

```bash
make         # lists the targets
make build   # once, to install the web dependencies
make dev     # API with reload on :8321, web dev server on :5173
make test    # Python and web tests
```

## Where things live

- `data/` holds the database, recordings and casts under `data/audio/`, the art packs under `data/art/`, and the files you add to a course under `data/sources/` (PDF, EPUB, HTML, Markdown, text, code; the tutor searches them and reads one section at a time). Before a schema upgrade the database is copied to `data/wise-scholar.db.v<N>.bak`.
- `workspace/<course>/` holds each course's exercise files. Deleting a course removes its folder.
- `.mcp.json` and `opencode.json` declare the tutor's MCP server for this repository only.
