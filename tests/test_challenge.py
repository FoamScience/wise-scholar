from wise_scholar import challenge


def test_reveal_gate_opens_only_after_attempts_give_up_or_solve():
    data = challenge.new()
    assert "3 more" in challenge.reveal_blocker(data)
    data["attempts"] = ["a", "b"]
    assert "1 more" in challenge.reveal_blocker(data)
    data["attempts"].append("c")
    assert challenge.reveal_blocker(data) is None

    assert challenge.reveal_blocker({**challenge.new(), "gave_up": True}) is None
    assert challenge.reveal_blocker({**challenge.new(), "solved": True}) is None
    assert "already shown" in challenge.reveal_blocker({**challenge.new(), "gave_up": True, "solution": "x"})


def test_hint_ladder_stops_at_max_and_on_closed_challenges(hints):
    data = challenge.new()
    assert challenge.hint_blocker(data) is None
    data["hints"] = ["1", "2", "3"]
    assert "used up" in challenge.hint_blocker(data)
    assert "closed" in challenge.hint_blocker({**challenge.new(), "solved": True})


def test_without_the_hints_setting_a_challenge_has_no_ladder_and_a_writing_task_keeps_its_prompts(monkeypatch):
    from wise_scholar import app

    monkeypatch.setattr(challenge, "HINTS", False)
    assert challenge.new()["max_hints"] == 0 and "no hint ladder" in challenge.hint_blocker(challenge.new())
    assert challenge.new(reveal_after=2, max_hints=challenge.MAX_HINTS)["max_hints"] == challenge.MAX_HINTS
    assert any("no hint ladder" in line for line in app._tool_lines())
    monkeypatch.setattr(challenge, "HINTS", True)
    assert challenge.new()["max_hints"] == challenge.MAX_HINTS
    assert not any("no hint ladder" in line for line in app._tool_lines())
