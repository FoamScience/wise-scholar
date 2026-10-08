from wise_scholar import challenge
from wise_scholar.history import RECENT_LESSONS, digest


def block(kind, markdown, data=None):
    return {"kind": kind, "markdown": markdown, "data": data}


def test_digest_reports_tasks_with_outcomes():
    solved = {**challenge.new(), "attempts": ["a", "b"], "hints": ["h"], "solved": True}
    gave_up = {**challenge.new(), "attempts": ["a"], "gave_up": True, "files": ["m/x.py"], "run": "python3 m/x.py"}
    writing = {**challenge.new(2), "writing": True}
    lesson = {
        "title": "Names and objects",
        "blocks": [
            block("challenge", "Predict   the\noutput " + "x" * 300, solved),
            block("exercise", "Fix scale_residuals", gave_up),
            block("challenge", "Schreib zwei Sätze", writing),
            block("quiz", "What is a?", {"answer": "3", "confidence": 0.9, "correct": False, "confident_miss": True}),
            block("quiz", "What is b?", {"answer": None}),
            block("reading", "Am Montag …", {"title": "Ein langer Montag"}),
            block("prose", "## Rule\nThe verb is second."),
        ],
    }
    lines = digest([lesson]).splitlines()
    assert lines[0] == "- Names and objects:"
    assert lines[1].startswith("  - challenge: Predict the output xxx") and lines[1].endswith("… -> solved, 2 attempt(s), 1 hint(s)")
    assert lines[2] == "  - exercise (m/x.py): Fix scale_residuals -> gave up, 1 attempt(s)"
    assert lines[3] == "  - writing: Schreib zwei Sätze -> left open, 0 attempt(s)"
    assert lines[4] == "  - quiz: What is a? -> wrong at 90% sure (confident miss)"
    assert lines[5] == "  - quiz: What is b? -> not answered"
    assert lines[6] == "  - reading: Ein langer Montag"
    assert lines[7] == "  - taught: ## Rule The verb is second."


def test_digest_keeps_only_recent_lessons_and_marks_empty_ones():
    lessons = [{"title": f"L{i}", "blocks": []} for i in range(RECENT_LESSONS + 2)]
    text = digest(lessons)
    assert "- L0:" not in text and "- L1:" not in text and f"- L{RECENT_LESSONS + 1}:" in text
    assert "opened, nothing done yet" in text
    assert digest([]) == ""


def test_the_record_names_the_opening_form():
    from wise_scholar import history

    block = {"kind": "challenge", "markdown": "Find the flaw.", "data": {"attempts": ["x"], "solved": True, "hints": [], "gave_up": False, "form": "bug hunt"}}
    assert history._line(block).startswith("challenge: [opening: bug hunt] Find the flaw. ->")
