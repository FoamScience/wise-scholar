import os

# "<backend>" or "<backend>/<model>", e.g. "claude/sonnet" or "opencode/openrouter/qwen/qwen3.8-27b:free".
AGENT = os.environ.get("WISE_SCHOLAR_AGENT", "claude")
BACKEND, _, MODEL = AGENT.partition("/")
if BACKEND not in ("claude", "opencode"):
    raise SystemExit(f"WISE_SCHOLAR_AGENT must start with 'claude' or 'opencode', got {AGENT!r}")

# The port this server listens on; the backends point their MCP config at it, so several instances can run at once.
PORT = int(os.environ.get("WISE_SCHOLAR_PORT", "8321"))
MCP_URL = f"http://127.0.0.1:{PORT}/mcp"
