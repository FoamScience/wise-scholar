import os
import secrets

# "<backend>" or "<backend>/<model>", e.g. "claude/sonnet" or "opencode/openrouter/qwen/qwen3.8-27b:free".
AGENT = os.environ.get("WISE_SCHOLAR_AGENT", "claude")
BACKEND, _, MODEL = AGENT.partition("/")
if BACKEND not in ("claude", "opencode"):
    raise SystemExit(f"WISE_SCHOLAR_AGENT must start with 'claude' or 'opencode', got {AGENT!r}")

# The port this server listens on; the backends point their MCP config at it, so several instances can run at once.
PORT = int(os.environ.get("WISE_SCHOLAR_PORT", "8321"))
MCP_URL = f"http://127.0.0.1:{PORT}/mcp"
# Only the agents this process starts know the secret, so nothing else on the machine can call the tutor's tools.
# Set it to use the repository's own .mcp.json from a Claude Code session.
MCP_SECRET = os.environ.get("WISE_SCHOLAR_MCP_SECRET") or secrets.token_urlsafe(32)
MCP_HEADERS = {"Authorization": f"Bearer {MCP_SECRET}"}
TURN_HEADER = "X-Scholar-Turn"
# Phases whose prompt stands alone, without the tutor rules of core.md.
ALONE = ("graph",)

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
