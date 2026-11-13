from wise_scholar import backends


def test_claude_picks_a_model_per_kind_unless_one_is_named(monkeypatch):
    monkeypatch.setattr(backends, "BACKEND", "claude")
    monkeypatch.setattr(backends, "MODEL", "")
    monkeypatch.setattr(backends, "MODELS", {})
    assert [backends.model_for(p) for p in ("lesson-teacher", "practice", "story", "writing", "placement", "graph", "cards")] == [
        "opus", "opus", "opus", "opus", "sonnet", "sonnet", "haiku"]
    monkeypatch.setattr(backends, "MODELS", backends.parse_models("cards=sonnet"))
    assert backends.model_for("cards") == "sonnet" and backends.model_for("lesson") == "opus"
    monkeypatch.setattr(backends, "MODEL", "sonnet")
    assert backends.model_for("lesson") == "sonnet" and backends.model_for("cards") == "sonnet"


def test_other_backends_keep_one_model_for_every_kind(monkeypatch):
    monkeypatch.setattr(backends, "BACKEND", "opencode")
    monkeypatch.setattr(backends, "MODELS", {})
    monkeypatch.setattr(backends, "MODEL", "")
    assert {backends.model_for(k) for k in backends.KINDS} == {""}
    monkeypatch.setattr(backends, "MODEL", "openrouter/x")
    monkeypatch.setattr(backends, "MODELS", backends.parse_models("cards=openrouter/free"))
    assert backends.model_for("lesson") == "openrouter/x" and backends.model_for("cards") == "openrouter/free"
