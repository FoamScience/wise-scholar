import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db  # noqa: E402


def test_each_turn_records_its_tokens_and_cost_against_its_lesson_and_course(monkeypatch):
    import asyncio

    from wise_scholar import app
    from wise_scholar.routes import learner as learner_routes

    used = {"model": "claude-opus-5-5", "input": 10, "output": 200, "cache_read": 5000, "cache_write": 800, "cost": 0.25}

    async def run_turn(prompt, **kwargs):
        yield {"type": "chat.delta", "text": "Hi"}
        yield {"type": "turn.done", "ok": True, "error": None, "usage": used}

    monkeypatch.setattr(app.backend, "run_turn", run_turn)
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Spender')").lastrowid
    course = db.create_course("Impellers", who)["id"]
    lesson = db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"])
    for _ in range(2):
        app._turns[lesson["id"]] = None
        asyncio.run(app._run_turn(lesson, "[learner] go", quiet=True))
    asyncio.run(app._background_turn(lesson, "record", "graph", "claims"))

    [report] = learner_routes.list_usage(who)
    assert report["topic"] == "Impellers" and report["turns"] == 3 and report["cost"] == 0.75
    assert (report["input"], report["output"], report["cache_read"], report["cache_write"]) == (30, 600, 15000, 2400)
    [row] = report["lessons"]
    assert row["id"] == lesson["id"] and row["title"] == lesson["title"] and row["turns"] == 3
    assert {k["kind"]: k["turns"] for k in report["kinds"]} == {lesson["phase"]: 2, "graph": 1}
    assert learner_routes.list_usage(db.conn.execute("INSERT INTO profiles (name) VALUES ('Saver')").lastrowid) == []

    db.delete_course(course)
    assert learner_routes.list_usage(who) == [] and db.row("SELECT COUNT(*) AS n FROM usage WHERE course_id = ?", course)["n"] == 0


def test_a_lesson_idle_past_the_cache_hour_goes_on_in_a_fresh_session_from_its_record(monkeypatch):
    import asyncio

    from wise_scholar import app

    calls = []

    async def run_turn(prompt, **kwargs):
        calls.append({"prompt": prompt, **kwargs})
        yield {"type": "session.started", "session_id": kwargs["session_id"]}
        yield {"type": "turn.done", "ok": True, "error": None,
               "usage": {"model": "m", "input": 1, "output": 1, "cache_read": 1, "cache_write": 1, "cost": 0.0}}

    monkeypatch.setattr(app.backend, "run_turn", run_turn)
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Idle returner')").lastrowid
    course = db.create_course("Rotors", who)["id"]
    lesson_id = db.create_lesson(course, "Blades", "lesson")
    db.add_message(lesson_id, "learner", "the blade twists toward the hub")

    def turn():
        app._turns[lesson_id] = None
        asyncio.run(app._run_turn(db.lesson(lesson_id), "[learner] next", quiet=True))
        return calls[-1]

    first, again = turn(), turn()
    assert not first["resume"] and again["resume"] and again["session_id"] == first["session_id"]
    assert "[so far]" not in again["prompt"]

    db.conn.execute("UPDATE usage SET created = datetime('now', '-61 minutes') WHERE lesson_id = ?", (lesson_id,))
    cold = turn()
    assert not cold["resume"] and cold["session_id"] != first["session_id"]
    assert db.lesson(lesson_id)["session_id"] == cold["session_id"]
    assert "the blade twists toward the hub" in cold["prompt"] and cold["prompt"].index("[so far]") < cold["prompt"].index("[learner] next")

    # Past the limit the record keeps the end of the lesson, where the learner left off.
    for n in range(60):
        db.add_message(lesson_id, "tutor", f"step {n}: " + "x" * 900)
    record = app._lesson_record(lesson_id, newest=True)
    assert len(record) == app.RECORD_CHARS and "step 59:" in record and "the blade twists" not in record

    # A lesson from before usage was recorded goes cold by the tutor's last reply.
    db.conn.execute("DELETE FROM usage WHERE lesson_id = ?", (lesson_id,))
    assert app._resumes(db.lesson(lesson_id))
    db.conn.execute("UPDATE messages SET created = datetime('now', '-2 hours') WHERE lesson_id = ?", (lesson_id,))
    assert not app._resumes(db.lesson(lesson_id))


def test_a_backend_that_raises_ends_the_turn_as_failed_instead_of_losing_it(monkeypatch):
    import asyncio

    from wise_scholar import app

    published = []

    async def run_turn(prompt, **kwargs):
        yield {"type": "chat.delta", "text": "Half"}
        raise RuntimeError("boom")

    monkeypatch.setattr(app.backend, "run_turn", run_turn)
    monkeypatch.setattr(app.hub, "publish", lambda course_id, event: published.append(event))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Unlucky')").lastrowid
    course = db.create_course("Seals", who)["id"]
    lesson = db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"])
    app._turns[lesson["id"]] = None
    asyncio.run(app._run_turn(lesson, "[learner] go"))

    assert lesson["id"] not in app._turns
    done = published[-1]
    assert done["type"] == "turn.done" and not done["ok"] and "server log" in done["error"]
    assert done["message"]["text"] == "Half"


def test_a_resumed_session_is_charged_per_turn_not_its_running_total():
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Resumer')").lastrowid
    course = db.create_course("Pumps", who)["id"]
    lesson = db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"]
    turn = {"model": "claude-opus-5-5", "input": 2, "output": 10, "cache_read": 100, "cache_write": 50}
    for running in (0.25, 0.75, 1.0):
        db.add_usage(course, lesson, "lesson", "claude", {**turn, "cost": running, "session": "a"})
    db.add_usage(course, lesson, "lesson", "claude", {**turn, "cost": 0.5, "session": "b"})
    db.add_usage(course, lesson, "graph", "opencode", {**turn, "cost": 0.125})
    costs = [r["cost"] for r in db.rows("SELECT cost FROM usage WHERE course_id = ? ORDER BY id", course)]
    assert costs == [0.25, 0.5, 0.25, 0.5, 0.125]
