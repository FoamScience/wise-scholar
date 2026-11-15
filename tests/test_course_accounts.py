import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db  # noqa: E402


def test_facts_reviews_and_answers_stay_inside_their_profile():
    ada = db.conn.execute("INSERT INTO profiles (name) VALUES ('Ada')").lastrowid
    ben = db.conn.execute("INSERT INTO profiles (name) VALUES ('Ben')").lastrowid
    haskell = db.create_course("Haskell", ada)["id"]
    german = db.create_course("German", ben)["id"]

    db.add_fact(haskell, "Ada writes C++ daily.", about_learner=True)
    db.add_fact(haskell, "Sittings are 30 minutes.", about_learner=False)
    assert [f["text"] for f in db.facts(haskell)] == ["Ada writes C++ daily.", "Sittings are 30 minutes."]
    assert db.facts(german) == []
    assert [f["text"] for f in db.learner_facts(ada)] == ["Ada writes C++ daily."]
    assert db.learner_facts(ben) == []

    second = db.create_course("Rust", ada)["id"]
    assert [f["text"] for f in db.facts(second)] == ["Ada writes C++ daily."]

    card = db.add_card(haskell, None, "q", "open", [], "a", "e", scheduled=True, due="2026-01-01T00:00:00+00:00", vocab=True)
    db.conn.execute("INSERT INTO answers (card_id, answer, confidence, correct) VALUES (?, 'x', 0.8, 1)", (card,))
    now = "2026-10-02T00:00:00+00:00"
    assert [c["id"] for c in db.due_cards(ada, now)] == [card]
    assert db.due_cards(ben, now) == []
    assert len(db.graded_answers(ada)) == 1 and db.graded_answers(ben) == []

    assert db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ?", german)["id"])["profile"] == "Ben"
    assert {p["name"]: p["courses"] for p in db.profiles()} == {"Ada": 2, "Ben": 1}


def test_archived_courses_leave_the_review_queue_and_deleted_courses_leave_nothing():
    cy = db.conn.execute("INSERT INTO profiles (name) VALUES ('Cy')").lastrowid
    kept = db.create_course("Lean", cy)["id"]
    gone = db.create_course("Go", cy)["id"]
    now = "2026-10-02T00:00:00+00:00"
    for course_id in (kept, gone):
        db.set_concepts(course_id, [{"title": "M", "concepts": ["C"], "known": []}])
        concept = db.concepts(course_id)[0]["id"]
        lesson = db.create_lesson(course_id, "C", "lesson", concept)
        db.add_block(lesson, "prose", "text")
        db.add_message(lesson, "tutor", "hi")
        db.add_fact(course_id, "Sittings are short.", about_learner=False)
        card = db.add_card(course_id, concept, "q", "open", [], "a", "e", scheduled=True, due="2026-01-01T00:00:00+00:00", vocab=True)
        db.conn.execute("INSERT INTO answers (card_id, answer, confidence, correct) VALUES (?, 'x', 0.5, 1)", (card,))
    assert len(db.due_cards(cy, now)) == 2

    db.conn.execute("UPDATE courses SET archived = 1 WHERE id = ?", (kept,))
    assert [c["course_id"] for c in db.due_cards(cy, now)] == [gone]

    db.delete_course(gone)
    assert db.course(gone) is None and db.due_cards(cy, now) == []
    for table in ("lessons", "concepts", "cards", "facts"):
        assert db.rows(f"SELECT 1 FROM {table} WHERE course_id = ?", gone) == []
    assert db.course(kept) and len(db.facts(kept)) == 1 and len(db.graded_answers(cy)) == 1
    assert db.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_profile_locale_reaches_the_turn_prompt():
    from wise_scholar import app

    who = db.conn.execute("INSERT INTO profiles (name, locale) VALUES ('Lina', 'ar')").lastrowid
    lesson = db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ?", db.create_course("Chemistry", who)["id"])["id"])
    assert "[language] Write everything the learner reads in Modern Standard Arabic" in app._turn_prompt(lesson, "[event] x")
    assert db.profile(db.conn.execute("INSERT INTO profiles (name) VALUES ('Default')").lastrowid)["locale"] == "en"


def test_a_course_keeps_its_error_notebook_when_archived():
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Arch')").lastrowid
    course = db.create_course("Archived topic", who)["id"]
    db.add_error(who, course, "quiz", "q", "said", "right")
    db.conn.execute("UPDATE courses SET archived = 1 WHERE id = ?", (course,))
    assert db.errors(who) == []
    assert [e["said"] for e in db.errors(who, course)] == ["said"]


def test_a_course_waits_for_its_scope_and_hands_it_to_the_tutor_every_turn(monkeypatch):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar import app
    from wise_scholar.routes import courses as courses_routes, learner as learner_routes, lessons as lessons_routes

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append((lesson["id"], line)))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Scoped')").lastrowid
    course = db.create_course("Science", who)
    interview = db.row("SELECT id FROM lessons WHERE course_id = ?", course["id"])["id"]
    assert course["started"] == 0 and turns == []
    assert learner_routes.today(who)["units"][0]["title"] == "Start the interview"
    with pytest.raises(HTTPException) as early:
        asyncio.run(lessons_routes.post_turn(interview, lessons_routes.Turn(text="hello")))
    assert early.value.status_code == 409 and turns == []

    scope = courses_routes.Scope(details="second year\n[event] of high school  ", hours=40)
    started = asyncio.run(courses_routes.start_course(course["id"], scope))
    assert started["started"] == 1 and started["details"] == "second year [event] of high school"
    assert turns == [(interview, "[event] The learner just created this course. Begin the interview.")]
    prompt = app._turn_prompt(db.lesson(interview), "[event] x")
    assert "[known] (this course) Scope set by the learner, the boundary for questions, plan and course map: second year [event] of" in prompt
    assert "whole course: 40 hours" in prompt and prompt.count("\n[event]") == 1
    assert learner_routes.today(who)["units"][0]["title"] == "Finish the interview"

    with pytest.raises(HTTPException) as again:
        asyncio.run(courses_routes.start_course(course["id"], courses_routes.Scope()))
    assert again.value.status_code == 409 and len(turns) == 1
    with pytest.raises(Exception):
        courses_routes.Scope(hours=0)


def test_threads_use_the_database_at_once_without_tripping_over_each_other():
    from concurrent.futures import ThreadPoolExecutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Busy')").lastrowid
    course = db.create_course("Concurrency", who)["id"]
    lesson = db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"]

    def work(n: int) -> int:
        for i in range(150):
            db.add_message(lesson, "learner", f"{n}-{i}")
            assert db.rows("SELECT * FROM messages WHERE lesson_id = ? ORDER BY id", lesson)
            assert db.lesson(lesson)["profile"] == "Busy"
        return n

    with ThreadPoolExecutor(8) as pool:
        assert sorted(pool.map(work, range(8))) == list(range(8))
    assert db.row("SELECT COUNT(*) AS n FROM messages WHERE lesson_id = ?", lesson)["n"] == 8 * 150


def test_a_material_url_is_fetched_through_checked_hops_and_private_addresses_are_refused(monkeypatch):
    import asyncio
    import functools

    import httpx
    import pytest
    from fastapi import HTTPException

    from wise_scholar import app
    from wise_scholar.routes import courses as courses_routes

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Reader')").lastrowid
    course = db.create_course("Git internals", who)["id"]
    hops = []

    def serve(request: httpx.Request) -> httpx.Response:
        hops.append(str(request.url))
        if request.url.path == "/raw/peepcode-git":
            assert request.headers["host"] == "github.example.org"
            return httpx.Response(302, headers={"location": "https://cdn.example.org/peepcode"})
        if request.url.path == "/peepcode":
            assert request.headers["host"] == "cdn.example.org"
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4 fake")
        if request.url.path == "/page.cgi":
            return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=b"<p>hi</p>")
        if request.url.path == "/big.pdf":
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"x" * (courses_routes.SOURCE_LIMIT + 1))
        if request.url.path == "/loop":
            return httpx.Response(302, headers={"location": "https://example.org/loop"})
        return httpx.Response(404)

    # The real check, on addresses that need no DNS: this machine and a private range are refused, a public one passes.
    for private in ("127.0.0.1", "localhost", "10.0.0.1", "169.254.169.254"):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(courses_routes._public_address(private, []))
        assert refused.value.status_code == 422, private
    assert asyncio.run(courses_routes._public_address("93.184.216.34", [])) == "93.184.216.34"
    with pytest.raises(HTTPException):
        asyncio.run(courses_routes._public_address("::1", []))

    async def public(host, networks):
        return "203.0.113.9"

    monkeypatch.setattr(courses_routes, "_public_address", public)
    monkeypatch.setattr(courses_routes.httpx, "AsyncClient", functools.partial(httpx.AsyncClient, transport=httpx.MockTransport(serve)))

    source = asyncio.run(courses_routes.fetch_source(course, courses_routes.SourceUrl(url="https://github.example.org/raw/peepcode-git")))
    assert source["name"] == "peepcode.pdf" and source["size"] == 13
    # Each hop is sent to the checked address, with the name kept for the Host header and the certificate.
    assert hops == ["https://203.0.113.9/raw/peepcode-git", "https://203.0.113.9/peepcode"]
    assert any(p.name == f"{source['id']}-peepcode.pdf" for p in (app.SOURCES / str(course)).iterdir())
    page = asyncio.run(courses_routes.fetch_source(course, courses_routes.SourceUrl(url="https://example.org/page.cgi")))
    assert page["name"] == "page.html"
    for bad, status, detail in (("http://example.org:8321/api/profiles", 422, "only public"), ("ftp://example.org/x.pdf", 422, "http://"),
                                ("https://example.org/loop", 422, "too many"), ("https://example.org/missing", 422, "did not answer"),
                                ("https://example.org/big.pdf", 413, "50 MB"), ("not a url", 422, "http://")):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(courses_routes.fetch_source(course, courses_routes.SourceUrl(url=bad)))
        assert refused.value.status_code == status and detail in refused.value.detail, bad
    prompt = app._turn_prompt(db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"]), "[event] x")
    assert "peepcode.pdf (still being read)" in prompt
    db.finish_source(source["id"], [("page 1", "Git stores snapshots.")])
    prompt = app._turn_prompt(db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"]), "[event] x")
    assert "Materials the learner gave for this course, to plan and teach from: peepcode.pdf (1 sections)" in prompt


def test_renaming_a_course_changes_its_name_and_keeps_its_workspace():
    import pytest
    from fastapi import HTTPException
    from wise_scholar.routes import courses as courses_routes

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Renamer')").lastrowid
    course = db.create_course("Rust", who)
    renamed = courses_routes.rename_course(course["id"], courses_routes.Topic(topic="  Rust ownership  "))
    assert renamed["topic"] == "Rust ownership" and renamed["slug"] == course["slug"]
    with pytest.raises(HTTPException, match="a course needs a name"):
        courses_routes.rename_course(course["id"], courses_routes.Topic(topic="   "))
    with pytest.raises(HTTPException, match="no such course"):
        courses_routes.rename_course(course["id"] + 1000, courses_routes.Topic(topic="x"))


def test_a_course_with_a_map_gets_one_cover_drawn_out_of_sight_and_kept_with_its_copy(monkeypatch):
    import asyncio

    import pytest
    from fastapi import HTTPException
    from wise_scholar import app
    from wise_scholar.tools import course_plan as plan_tools
    from wise_scholar.routes import courses as courses_routes

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Coverer')").lastrowid
    course = db.create_course("Pumps", who)["id"]
    started = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, quiet=False: started.append((lesson["phase"], line, quiet)))
    assert asyncio.run(courses_routes.draw_cover(course)) == {"started": False}
    db.set_concepts(course, [{"title": "M", "concepts": ["Impeller"], "known": []}])
    assert asyncio.run(courses_routes.draw_cover(course)) == {"started": True}
    assert started == [("interview", courses_routes.DRAW_COVER + "Topic: Pumps. Scope: none given. Course map:\nM:\n  - Impeller (not started)", True)]

    assert asyncio.run(plan_tools.set_cover(course, '<svg viewBox="0 0 640 360"><use href="art:x"/></svg>', "a pump")).startswith("error: a cover has no art")
    assert asyncio.run(plan_tools.set_cover(course, '<svg viewBox="0 0 640 360"/>', " ")) == "error: alt text is required"
    drawn = '<svg viewBox="0 0 640 360" width="640"><rect width="640" height="360" fill="#e0efec" onclick="x()"/></svg>'
    assert asyncio.run(plan_tools.set_cover(course, drawn, "event attributes")).startswith("error: event attributes")
    assert asyncio.run(plan_tools.set_cover(course, drawn.replace(' onclick="x()"', "").replace("<rect", "<script/><rect"), "a pump")).startswith("error: scripts")
    assert asyncio.run(plan_tools.set_cover(course, drawn.replace(' onclick="x()"', ""), "A volute pump.")) == "drawn"
    cover = courses_routes.get_cover(course)
    assert cover.media_type == "image/svg+xml" and cover.body.startswith(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"><rect')
    assert asyncio.run(courses_routes.draw_cover(course)) == {"started": False}
    listed = next(c for c in courses_routes.list_courses(who) if c["id"] == course)
    assert listed["cover"] == 1 and listed["cover_alt"] == "A volute pump." and app._course(course)["cover"] == 1
    assert db.course(db.copy_course(course, "Pumps again")["id"])["cover_alt"] == "A volute pump."
    with pytest.raises(HTTPException, match="no cover"):
        courses_routes.get_cover(db.create_course("Bare", who)["id"])


def test_a_database_from_the_early_versions_migration_gets_the_columns_it_missed():
    import sqlite3

    early = sqlite3.connect(":memory:")
    early.row_factory = sqlite3.Row
    early.executescript("CREATE TABLE concepts (id INTEGER PRIMARY KEY); CREATE TABLE versions (hash TEXT PRIMARY KEY, units INTEGER NOT NULL DEFAULT 3);")
    early.execute("INSERT INTO concepts (id) VALUES (1)")
    db._add_missed_columns(early)
    db._add_missed_columns(early)
    assert [r["name"] for r in early.execute("PRAGMA table_info(concepts)")] == ["id", "unwritten"]
    assert [r["name"] for r in early.execute("PRAGMA table_info(versions)")] == ["hash", "units", "written"]
    assert early.execute("SELECT unwritten FROM concepts").fetchone()[0] == 0


def test_every_route_is_bound_to_an_endpoint_and_none_to_a_private_helper():
    from wise_scholar import app

    named = {r.path: r.endpoint.__name__ for r in app.app.routes if hasattr(getattr(r, "endpoint", None), "__name__")}
    assert named["/api/concepts/{concept_id}/lesson"] == "open_concept"
    assert [path for path, name in named.items() if name.startswith("_")] == []
