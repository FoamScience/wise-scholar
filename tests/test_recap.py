import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException

from wise_scholar import app, db, recap, tutor

NOW = "2026-11-09T12:00:00+00:00"


def _learner(mode: str = "learner") -> int:
    return db.conn.execute("INSERT INTO profiles (name, mode) VALUES (?, ?)", (f"Learner {uuid4()}", mode)).lastrowid


def _course(profile: int, modules: list[dict]) -> tuple[int, dict[str, int]]:
    course = db.create_course("Pumps", profile)["id"]
    db.set_concepts(course, modules)
    return course, {c["title"]: c["id"] for c in db.concepts(course)}


def _finish(course: int, concept: int, at: str) -> int:
    lesson = db.create_lesson(course, "Unit", "lesson", concept)
    db.conn.execute("INSERT INTO blocks (lesson_id, kind, markdown, data, created) VALUES (?, 'done', 'done', '{}', ?)", (lesson, at))
    return lesson


def _missed(profile: int, course: int, concept: int, at: str) -> tuple[int, int]:
    card = db.add_card(course, concept, "Which head?", "choice", ["a", "b"], "a", "", True)
    db.conn.execute("INSERT INTO answers (card_id, answer, confidence, correct, created) VALUES (?, 'b', 0.9, 0, ?)", (card, at))
    error = db.add_error(profile, course, "quiz", "Which head?", "b", "a", card_id=card)
    db.conn.execute("UPDATE errors SET created = ? WHERE id = ?", (at, error))
    return card, error


PUMPS = [{"title": "Flow", "concepts": ["Head", "Losses"], "known": ["Losses"]}, {"title": "Design", "concepts": ["Blades"], "known": []}]


def test_a_course_is_finished_once_every_module_is_done_and_growing_takes_the_finish_away():
    who = _learner()
    course, units = _course(who, PUMPS)
    _finish(course, units["Head"], "2026-10-05 10:00:00")
    assert db.course_finished(course) is None
    assert db.sync_recap(course) is None

    _finish(course, units["Blades"], "2026-10-12 10:00:00")
    assert db.course_finished(course) == "2026-10-12 10:00:00"
    state = db.sync_recap(course)
    assert (state["finished"], state["seen"]) == ("2026-10-12 10:00:00", 0)
    db.set_recap(course, seen=1, narrative={"intro": "x"})

    db.conn.execute("INSERT INTO concepts (course_id, module, title, position) VALUES (?, 'Design', 'Casing', 9)", (course,))
    state = db.sync_recap(course)
    assert state["finished"] is None
    assert state["narrative"] == {"intro": "x"}

    _finish(course, db.row("SELECT id FROM concepts WHERE course_id = ? AND title = 'Casing'", course)["id"], "2026-10-20 10:00:00")
    state = db.sync_recap(course)
    assert (state["finished"], state["seen"]) == ("2026-10-20 10:00:00", 0)


def test_a_module_whose_projects_are_all_built_counts_as_done():
    who = _learner()
    course, units = _course(who, [{"title": "Flow", "concepts": ["Head", "Losses"], "known": []}])
    _finish(course, units["Head"], "2026-10-05 10:00:00")
    db.add_capstone(course, "Flow", "Pump sizer", "", "sizer", [(units["Head"], "sizer.py")])
    assert db.course_finished(course) is None
    db.finish_milestone(db.capstones(course)[0]["milestones"][0]["id"])
    assert db.course_finished(course) == "2026-10-05 10:00:00"


def test_a_prepared_course_never_finishes():
    course, units = _course(_learner("teacher"), [{"title": "Flow", "concepts": ["Head"], "known": []}])
    db.conn.execute("UPDATE courses SET mode = 'teacher' WHERE id = ?", (course,))
    _finish(course, units["Head"], "2026-10-05 10:00:00")
    assert db.course_finished(course) is None


def test_the_story_tells_each_unit_with_its_claims_its_mistakes_put_right_and_its_project():
    who = _learner()
    course, units = _course(who, PUMPS)
    head = _finish(course, units["Head"], "2026-10-07 10:00:00")
    blades = _finish(course, units["Blades"], "2026-10-14 10:00:00")
    ids = db.record_claims(who, head, [{"key": "a", "text": "Head is energy per weight.", "evidence": []}], [])
    db.record_claims(who, blades, [{"key": "b", "text": "Blade angle sets the head.", "evidence": []}], [])
    card, error = _missed(who, course, units["Head"], "2026-10-06 09:00:00")
    db.conn.execute("INSERT INTO answers (card_id, answer, confidence, correct, created) VALUES (?, 'a', 0.8, 1, '2026-10-09 09:00:00')", (card,))
    _missed(who, course, units["Blades"], "2026-10-13 09:00:00")
    db.add_capstone(course, "Design", "Pump sizer", "", "sizer", [(units["Blades"], "sizer.py")])
    db.finish_milestone(db.capstones(course)[0]["milestones"][0]["id"])
    db.sync_recap(course)

    s = recap.story(course, NOW)
    assert [u["title"] for u in s["before"]] == ["Losses"]
    assert [(x["title"], x["week"]) for x in s["steps"]] == [("Head", "2026-10-05"), ("Blades", "2026-10-12")]
    assert s["weeks"] == ["2026-10-05", "2026-10-12"]
    assert s["steps"][0]["claims"] == [ids["a"]]
    assert s["steps"][1]["milestone"] == {"project": "Pump sizer", "deliverable": "sizer.py"}
    fixed = next(m for m in s["mistakes"] if m["id"] == error)
    assert (fixed["fixed"], fixed["put_right"], fixed["step"]) == ("2026-10-09 09:00:00", True, 0)
    assert s["stats"] | {"minutes": 0} == {
        "minutes": 0, "estimated": True, "units_done": 3, "units": 3, "projects_done": 1, "projects": 1,
        "claims_held": 0, "claims": 2, "mistakes_fixed": 1, "mistakes": 2,
    }
    assert s["started"] == "2026-10-06 09:00:00"
    assert s["finished"] == "2026-10-14 10:00:00"
    lines = recap.outline(s)
    assert "[week 2026-10-05]" in lines and "[project] Pump sizer: sizer.py" in lines and "[open mistake] Which head?" in lines


@pytest.fixture
def writer(monkeypatch):
    """Stands in for the tutor: the recap turn writes one caption per week it was given."""
    seen = []

    async def turn(lesson, prompt, kind, what):
        assert kind == "recap"
        seen.append(prompt)
        job = tutor.recap_jobs[lesson["course_id"]]
        weeks = [tutor.WeekCaption(week=w, caption=f"Week {w}.") for w in job["weeks"]]
        seen.append(await tutor.write_recap(lesson["course_id"], "Where you began.", weeks, "What you can do now."))
        return True

    monkeypatch.setattr(app, "_background_turn", turn)
    return seen


async def _open(course: int, preview: bool = False) -> dict:
    story = await app.get_recap(course, preview)
    if task := app._recapping.get(course):
        await task
    return story


def test_opening_a_finished_course_writes_its_narrative_once(writer):
    who = _learner()
    course, units = _course(who, PUMPS)
    db.create_lesson(course, "Interview", "interview")
    _finish(course, units["Head"], "2026-10-07 10:00:00")
    with pytest.raises(HTTPException) as refused:
        asyncio.run(_open(course))
    assert refused.value.status_code == 409

    _finish(course, units["Blades"], "2026-10-14 10:00:00")
    first = asyncio.run(_open(course))
    assert first["writing"] and first["narrative"] is None
    assert writer[-1] == "recorded"
    assert "[week 2026-10-12]" in writer[0]
    narrative = db.recap(course)["narrative"]
    assert narrative == {"intro": "Where you began.", "weeks": {"2026-10-05": "Week 2026-10-05.", "2026-10-12": "Week 2026-10-12."},
                         "letter": "What you can do now.", "locale": "en", "finished": "2026-10-14 10:00:00"}
    again = asyncio.run(_open(course))
    assert not again["writing"] and again["narrative"] == narrative
    assert len(writer) == 2


def test_the_recap_tool_wants_every_week_and_only_those():
    course, _ = _course(_learner(), PUMPS)
    tutor.recap_jobs[course] = {"weeks": ["2026-10-05"], "locale": "en", "finished": "x", "done": False}
    try:
        write = lambda weeks, intro="Start.": asyncio.run(tutor.write_recap(course, intro, weeks, "Letter."))
        assert write([]) == "error: weeks ['2026-10-05'] need a caption"
        two = [tutor.WeekCaption(week="2026-10-05", caption="One."), tutor.WeekCaption(week="2026-10-12", caption="Two.")]
        assert write(two).startswith("error: ['2026-10-12'] are not weeks")
        assert write([two[0]], intro="x" * 800).startswith("error: the intro")
    finally:
        tutor.recap_jobs.pop(course)
    assert asyncio.run(tutor.write_recap(course, "Start.", [], "Letter.")) == f"error: no recap is being written on course {course}"


def test_an_unfinished_course_opens_as_a_preview_only_where_the_server_allows_it(writer, monkeypatch):
    who = _learner()
    course, units = _course(who, PUMPS)
    _finish(course, units["Head"], "2026-10-07 10:00:00")
    with pytest.raises(HTTPException):
        asyncio.run(_open(course, preview=True))
    monkeypatch.setattr(app, "RECAP_PREVIEW", True)
    story = asyncio.run(_open(course, preview=True))
    assert story["preview"] and not story["writing"] and writer == []


def test_the_course_list_and_detail_say_when_a_course_was_finished():
    who = _learner()
    course, units = _course(who, PUMPS)
    _finish(course, units["Head"], "2026-10-07 10:00:00")
    _finish(course, units["Blades"], "2026-10-14 10:00:00")
    assert app._course(course)["recap"] == {"finished": "2026-10-14 10:00:00", "seen": False}
    app.see_recap(course)
    assert app._course(course)["recap"]["seen"] is True
    assert app.list_courses(who)[0]["finished"] == "2026-10-14 10:00:00"
    app.save_recap_layout(course, app.RecapLayout(positions={3: (1.5, 2.0)}))
    assert db.recap(course)["positions"] == {"3": [1.5, 2.0]}


def test_a_recap_turn_that_breaks_tells_the_open_page(monkeypatch):
    async def broken(lesson, prompt, kind, what):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(app, "_background_turn", broken)
    published = []
    monkeypatch.setattr(app.hub, "publish", lambda course, event: published.append((course, event)))
    course, units = _course(_learner(), PUMPS)
    db.create_lesson(course, "Interview", "interview")
    _finish(course, units["Head"], "2026-10-07 10:00:00")
    _finish(course, units["Blades"], "2026-10-14 10:00:00")
    asyncio.run(_open(course))
    assert published == [(course, {"type": "recap.written"})]
    assert course in app._recap_failed
    assert not asyncio.run(_open(course))["writing"]
