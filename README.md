<p align="center"><img src="docs/hero.svg" alt="Wise Scholar" width="880"></p>

A self-hosted AI tutor with a web interface. It interviews you, picks a teaching approach for the topic, and teaches through hints, exercises, confidence-rated quick checks and spaced reviews. The tutor runs through [Claude Code](https://claude.com/claude-code) or [opencode](https://opencode.ai) on your own machine.

## Run

Needs [uv](https://docs.astral.sh/uv/) with Python 3.11 or newer, Node.js, [bubblewrap](https://github.com/containers/bubblewrap) on Linux, and `claude` or `opencode` logged in on your `PATH`.

```bash
make help # -> on how install special modules, start the server, run tests, etc.
make serve # -> start the server with Claude Code backend
```

Open <http://127.0.0.1:8321> and start a course. `WISE_SCHOLAR_AGENT=opencode make serve` picks the other backend.

## More

- [docs/guide.md](docs/guide.md): backends and models, languages, PDF export, speech, art packs, diagrams, what the sandbox allows, every setting, how to develop.
- [docs/science.md](docs/science.md): the research behind each teaching behaviour.
