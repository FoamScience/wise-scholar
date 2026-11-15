from wise_scholar.backends import MCP_URL, opencode


def test_opencode_reaches_the_tutor_and_only_follows_a_gateway_when_one_is_named(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    assert opencode.config() == {"mcp": {"scholar": {"type": "remote", "url": MCP_URL, "enabled": True, "headers": opencode.MCP_HEADERS}}}
    for base in ("https://llm.example.com", "https://llm.example.com/", "https://llm.example.com/v1", "https://llm.example.com/v1/"):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", base)
        assert opencode.config()["provider"] == {"anthropic": {"options": {"baseURL": "https://llm.example.com/v1"}}}
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "")
    assert "provider" not in opencode.config()
