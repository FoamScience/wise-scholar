import ast
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import app, challenge  # noqa: E402
from wise_scholar.playbooks import PLAYBOOKS  # noqa: E402

ROOT = Path(__file__).parent.parent
LOCALES = {code: json.loads((ROOT / "web/src/locales" / f"{code}.json").read_text()) for code in ("en", "fr", "ar")}


def learner_errors() -> set[str]:
    """The details a learner can trigger: the text of every 409, 413 and 422 the app raises, and the hint blockers.
    A detail held in a variable is one of the hint blockers; 404s and 503s are programming or service faults."""
    found = set()
    for node in ast.walk(ast.parse((ROOT / "wise_scholar/app.py").read_text())):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "HTTPException"):
            continue
        status, detail = node.args
        if status.value not in (409, 413, 422) or isinstance(detail, ast.Name):
            continue
        found.add(eval(compile(ast.Expression(detail), "app.py", "eval"), vars(app)))
    closed = {**challenge.new(), "solved": True}
    used_up = {**challenge.new(), "hints": ["h"] * challenge.MAX_HINTS}
    return found | {challenge.hint_blocker(closed), challenge.hint_blocker(used_up)}


def test_every_learner_facing_server_error_is_translated():
    errors = learner_errors()
    assert "already answered" in errors and f"a course holds at most {app.SOURCES_PER_COURSE} files" in errors
    for code in ("fr", "ar"):
        assert errors - set(LOCALES[code]["server"]) == set()


def test_every_playbook_has_a_title_and_summary_in_each_language():
    for locale in LOCALES.values():
        assert set(locale["translation"]["playbooks"]) == set(PLAYBOOKS)


def test_server_written_sentences_exist_in_each_language_with_their_slot():
    assert set(app.LOCALE_NAMES) == set(app.WORD_CARD) == set(LOCALES)
    for question, source in app.WORD_CARD.values():
        assert question.count("{}") == source.count("{}") == 1
