"""agy's PreToolUse hook: only the tutor's MCP tools run, plus reading their schemas, which agy loads lazily from its
own data folder before a first call. Every built-in tool (shell, files, browser, web, subagents) is denied."""

import json
import os
import sys


def decide(call: dict, schemas: str) -> str:
    name, args = call.get("name"), call.get("args") or {}
    if name == "call_mcp_tool":
        return "allow" if args.get("ServerName") == "scholar" else "deny"
    if name in ("read_file", "view_file"):
        path = os.path.realpath(args.get("Path") or args.get("AbsolutePath") or "")
        return "allow" if path.startswith(os.path.join(schemas, "")) and path.endswith(".json") else "deny"
    return "deny"


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    print(json.dumps({"decision": decide(payload.get("toolCall") or {}, os.path.realpath(sys.argv[1])),
                      "reason": "only the scholar tools are available"}))
