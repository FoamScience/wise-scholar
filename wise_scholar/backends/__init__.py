import os
import secrets
from pathlib import Path

# "<backend>" or "<backend>/<model>", e.g. "claude/sonnet", "opencode/openrouter/qwen/qwen3.8-27b:free",
# "agy/gemini-3.8-flash-high" or "anthropic/claude-sonnet-5-5".
AGENT = os.environ.get("WISE_SCHOLAR_AGENT", "claude")
BACKEND, _, MODEL = AGENT.partition("/")
BACKENDS = ("claude", "opencode", "agy", "anthropic")
if BACKEND not in BACKENDS:
    raise SystemExit(f"WISE_SCHOLAR_AGENT must start with 'claude', 'opencode', 'agy' or 'anthropic', got {AGENT!r}")

# The port this server listens on; the backends point their MCP config at it, so several instances can run at once.
PORT = int(os.environ.get("WISE_SCHOLAR_PORT", "8321"))
MCP_URL = f"http://127.0.0.1:{PORT}/mcp"
# Only the agents this process starts know the secret, so nothing else on the machine can call the tutor's tools.
# Set it to use the repository's own .mcp.json from a Claude Code session.
MCP_SECRET = os.environ.get("WISE_SCHOLAR_MCP_SECRET") or secrets.token_urlsafe(32)
MCP_HEADERS = {"Authorization": f"Bearer {MCP_SECRET}"}
TURN_HEADER = "X-Scholar-Turn"
# Phases whose prompt stands alone, without the tutor rules of core.md.
ALONE = ("graph", "cards", "cleanup", "explore", "recap", "contribute", "gist")
KINDS = ("interview", "placement", "lesson", "practice", "revisit", "story", "writing", "roleplay", "contribution", *ALONE)
PROMPTS = Path(__file__).resolve().parents[1] / "prompts"

# Claude Code and the Anthropic API get a model per kind by default: teaching on the strongest, narrow background jobs
# on cheaper ones. A model named in WISE_SCHOLAR_AGENT, or another backend's default, serves every kind.
CLAUDE_MODELS = {
    "interview": "opus", "lesson": "opus", "practice": "opus", "revisit": "opus", "story": "opus", "writing": "opus", "roleplay": "opus", "contribution": "opus",
    "placement": "sonnet", "graph": "sonnet", "cleanup": "sonnet", "explore": "sonnet", "recap": "sonnet", "contribute": "sonnet", "gist": "sonnet",
    "cards": "haiku",
}
API_MODELS = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}


def parse_models(value: str) -> dict[str, str]:
    """`kind=model` pairs, comma-separated; raises ValueError on an unknown kind or an empty model."""
    models = {}
    for pair in filter(None, (p.strip() for p in value.split(","))):
        kind, _, model = (part.strip() for part in pair.partition("="))
        if kind not in KINDS or not model:
            raise ValueError(f"{pair!r}: write kind=model, the kind one of {', '.join(KINDS)}")
        models[kind] = model
    return models


# Per-kind models over the default, e.g. "cards=haiku,graph=sonnet".
try:
    MODELS = parse_models(os.environ.get("WISE_SCHOLAR_MODELS", ""))
except ValueError as e:
    raise SystemExit(f"WISE_SCHOLAR_MODELS: {e}")


def model_for(phase: str) -> str:
    """The model a turn of this phase prompt runs on; empty for the backend's own default."""
    kind = phase.removesuffix("-teacher")
    if model := MODELS.get(kind) or MODEL:
        # Claude Code resolves opus, sonnet and haiku itself; the API takes only full ids.
        return API_MODELS.get(model, model) if BACKEND == "anthropic" else model
    if BACKEND == "claude":
        return CLAUDE_MODELS.get(kind, "")
    return API_MODELS[CLAUDE_MODELS[kind]] if BACKEND == "anthropic" else ""


def system_prompt(phase: str) -> str:
    """The tutor rules of core.md and the phase prompt, or the phase prompt alone for a phase that stands alone."""
    return "\n\n".join((PROMPTS / f"{part}.md").read_text() for part in ((phase,) if phase in ALONE else ("core", phase)))

# What an agent process gets from the server's environment: the basics, its own settings and keys, and whatever the
# owner lists in WISE_SCHOLAR_AGENT_ENV (names or prefixes ending in *), never the server's other secrets.
BASE_ENV = ("PATH", "HOME", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR",
            "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy", "XDG_CONFIG_HOME",
            "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR", "XDG_STATE_HOME")
EXTRA_ENV = [name.strip() for name in os.environ.get("WISE_SCHOLAR_AGENT_ENV", "").split(",") if name.strip()]


def environment(*patterns: str) -> dict[str, str]:
    """A minimal environment for an agent process: BASE_ENV plus every variable matching a pattern (a name, or a
    prefix ending in *), plus the owner's extras."""
    wanted = [*BASE_ENV, *patterns, *EXTRA_ENV]
    return {
        name: value
        for name, value in os.environ.items()
        if any(name == p or (p.endswith("*") and name.startswith(p[:-1])) for p in wanted)
    }
