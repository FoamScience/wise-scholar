import os

# "<backend>" or "<backend>/<model>", e.g. "claude/sonnet" or "opencode/openrouter/qwen/qwen3.8-27b:free".
AGENT = os.environ.get("WISE_SCHOLAR_AGENT", "claude")
BACKEND, _, MODEL = AGENT.partition("/")
if BACKEND not in ("claude", "opencode"):
    raise SystemExit(f"WISE_SCHOLAR_AGENT must start with 'claude' or 'opencode', got {AGENT!r}")
