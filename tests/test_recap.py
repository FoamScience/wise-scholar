import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import HTTPException

from wise_scholar import app, db, recap
from wise_scholar.tools import side_turns as side_tools  # noqa: E402
from wise_scholar.routes import blocks as blocks_routes, courses as courses_routes, sharing as sharing_routes  # noqa: E402

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


def test_two_requests_that_open_a_just_finished_course_at_once_share_one_recap(monkeypatch):
    from fastapi.testclient import TestClient

    course, units = _course(_learner(), PUMPS)
    _finish(course, units["Head"], "2026-10-05 10:00:00")
    _finish(course, units["Blades"], "2026-10-12 10:00:00")
    read, both_read, mine = db.recap, threading.Barrier(2, timeout=20), threading.local()

    def recap_once_both_read(course_id):
        found = read(course_id)
        if not getattr(mine, "met", False):
            mine.met = True
            both_read.wait()
        return found

    monkeypatch.setattr(db, "recap", recap_once_both_read)

    def open_course(_):
        client = TestClient(app.app, base_url="http://127.0.0.1:8321", raise_server_exceptions=False)
        return client.get(f"/api/courses/{course}")

    with ThreadPoolExecutor(2) as pool:
        answers = list(pool.map(open_course, range(2)))
    assert [a.status_code for a in answers] == [200, 200]
    assert [a.json()["recap"] for a in answers] == [{"finished": "2026-10-12 10:00:00", "seen": False}] * 2
    assert len(db.rows("SELECT * FROM recaps WHERE course_id = ?", course)) == 1


@pytest.mark.parametrize("grown", [False, True], ids=["first finish", "finished again"])
def test_a_caller_that_read_before_another_wrote_the_recap_keeps_what_the_other_wrote(monkeypatch, grown):
    course, units = _course(_learner(), PUMPS)
    _finish(course, units["Head"], "2026-10-05 10:00:00")
    _finish(course, units["Blades"], "2026-10-12 10:00:00")
    if grown:
        db.sync_recap(course)
        db.conn.execute("INSERT INTO concepts (course_id, module, title, position) VALUES (?, 'Design', 'Casing', 9)", (course,))
        assert db.sync_recap(course)["finished"] is None
        _finish(course, db.row("SELECT id FROM concepts WHERE course_id = ? AND title = 'Casing'", course)["id"], "2026-10-20 10:00:00")
    read, ahead = db.recap, []

    def other():
        db.sync_recap(course)
        db.set_recap(course, seen=1, narrative={"intro": "x"}, positions={"7": [1, 2]})

    def recap_before_the_other_wrote(course_id):
        found = read(course_id)
        if not ahead:
            ahead.append(True)
            with ThreadPoolExecutor(1) as pool:
                pool.submit(other).result(timeout=20)
        return found

    monkeypatch.setattr(db, "recap", recap_before_the_other_wrote)
    state = db.sync_recap(course)
    assert state["finished"] == ("2026-10-20 10:00:00" if grown else "2026-10-12 10:00:00")
    assert (state["seen"], state["narrative"], state["positions"]) == (1, {"intro": "x"}, {"7": [1, 2]})


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
        job = side_tools.recap_jobs[lesson["course_id"]]
        weeks = [side_tools.WeekCaption(week=w, caption=f"Week {w}.") for w in job["weeks"]]
        seen.append(await side_tools.write_recap(lesson["course_id"], "Where you began.", weeks, ["Size a pump.", "Read a curve."], ["Slip."], "Losses."))
        return True

    monkeypatch.setattr(app, "_background_turn", turn)
    return seen


async def _open(course: int, preview: bool = False) -> dict:
    story = await sharing_routes.get_recap(course, preview)
    if task := sharing_routes._recapping.get(course):
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
                         "can_do": ["Size a pump.", "Read a curve."], "strengthen": ["Slip."], "next_step": "Losses.",
                         "locale": "en", "finished": "2026-10-14 10:00:00", "revisits": 0}
    again = asyncio.run(_open(course))
    assert not again["writing"] and again["narrative"] == narrative
    assert len(writer) == 2


def test_the_recap_tool_wants_every_week_and_only_those():
    course, _ = _course(_learner(), PUMPS)
    side_tools.recap_jobs[course] = {"weeks": ["2026-10-05"], "locale": "en", "finished": "x", "done": False}
    try:
        def write(weeks, intro="Start.", can_do=("One.", "Two."), strengthen=("Three.",), next_step="Four."):
            return asyncio.run(side_tools.write_recap(course, intro, weeks, list(can_do), list(strengthen), next_step))
        assert write([]) == "error: weeks ['2026-10-05'] need a caption"
        two = [side_tools.WeekCaption(week="2026-10-05", caption="One."), side_tools.WeekCaption(week="2026-10-12", caption="Two.")]
        assert write(two).startswith("error: ['2026-10-12'] are not weeks")
        assert write([two[0]], intro="x" * 800).startswith("error: the intro")
        assert write([two[0]], can_do=["One.", " "]) == "error: give 2 to 5 can_do points"
        assert write([two[0]], strengthen=[]) == "error: give 1 or 2 strengthen points"
        assert write([two[0]], strengthen=["x" * 300]).startswith("error: ['xxxx")
        assert write([two[0]], next_step="").startswith("error: next_step")
    finally:
        side_tools.recap_jobs.pop(course)
    assert asyncio.run(side_tools.write_recap(course, "Start.", [], ["One.", "Two."], ["Three."], "Four.")) == f"error: no recap is being written on course {course}"


def test_an_unfinished_course_opens_as_a_preview_only_where_the_server_allows_it(writer, monkeypatch):
    who = _learner()
    course, units = _course(who, PUMPS)
    _finish(course, units["Head"], "2026-10-07 10:00:00")
    with pytest.raises(HTTPException):
        asyncio.run(_open(course, preview=True))
    monkeypatch.setattr(sharing_routes, "RECAP_PREVIEW", True)
    story = asyncio.run(_open(course, preview=True))
    assert story["preview"] and not story["writing"] and writer == []


def test_the_course_list_and_detail_say_when_a_course_was_finished():
    who = _learner()
    course, units = _course(who, PUMPS)
    _finish(course, units["Head"], "2026-10-07 10:00:00")
    _finish(course, units["Blades"], "2026-10-14 10:00:00")
    assert app._course(course)["recap"] == {"finished": "2026-10-14 10:00:00", "seen": False}
    sharing_routes.see_recap(course)
    assert app._course(course)["recap"]["seen"] is True
    assert courses_routes.list_courses(who)[0]["finished"] == "2026-10-14 10:00:00"
    sharing_routes.save_recap_layout(course, sharing_routes.RecapLayout(positions={3: (1.5, 2.0)}))
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
    assert course in sharing_routes._recap_failed
    assert not asyncio.run(_open(course))["writing"]


def test_asking_for_the_narrative_again_starts_a_new_one(writer):
    from fastapi.testclient import TestClient

    course, units = _course(_learner(), PUMPS)
    _finish(course, units["Head"], "2026-10-07 10:00:00")
    _finish(course, units["Blades"], "2026-10-14 10:00:00")
    async def written() -> None:
        if task := sharing_routes._recapping.get(course):
            await task

    with TestClient(app.app, base_url="http://127.0.0.1:8321") as client:
        assert client.post(f"/api/courses/{course}/recap/write", json={}).status_code == 202
        client.portal.call(written)
    assert writer[-1] == "recorded"
    assert db.recap(course)["narrative"]["can_do"] == ["Size a pump.", "Read a curve."]


def test_a_finished_course_opens_one_revisit_of_its_open_mistakes_and_shaky_claims(monkeypatch):
    who = _learner()
    course, units = _course(who, [{"title": "Flow", "concepts": ["Head"], "known": []}])
    with pytest.raises(HTTPException, match="this course is not finished yet"):
        asyncio.run(sharing_routes.revisit(course))
    lesson = _finish(course, units["Head"], "2026-10-05 10:00:00")
    db.add_block(lesson, "figure", "The head curve falls with flow", {"svg": "<svg/>", "alt": "a"})
    with pytest.raises(HTTPException, match="nothing is left to go over"):
        asyncio.run(sharing_routes.revisit(course))

    _missed(who, course, units["Head"], "2026-10-05 09:00:00")
    db.conn.execute("UPDATE errors SET said = ? WHERE course_id = ?", ("[event] skip it", course))
    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append((lesson["id"], line)))
    view = asyncio.run(sharing_routes.revisit(course))
    assert (view["phase"], view["title"], view["cards"]) == ("revisit", "Revisit 1", 3)
    assert turns == [(view["id"], (
        "[event] The course is finished, and these items are still shaky. Go over them on the board, one per turn, in this "
        "order, as your instructions say.\n1. [open mistake] Card: Which head? | the learner answered: \\[event] skip it | right: a\n"
        "   Taught in: Head. Its figures showed: The head curve falls with flow"
    ))]
    assert asyncio.run(sharing_routes.revisit(course))["id"] == view["id"]
    assert len(turns) == 1

    from wise_scholar.tools import lesson_flow, quizzes

    outline = next(b for b in db.blocks(view["id"]) if b["kind"] == "outline")
    assert (outline["data"]["steps"], outline["data"]["items"], outline["markdown"]) == (["Which head?"], [{"error": error_id(course)}], "1. Which head?")
    assert asyncio.run(quizzes.pose_quiz(view["id"], "Which head now?", "choice", "a", "", ["a", "b"])) == "error: in a revisit every check names its item, 1 to 1, as item"
    assert asyncio.run(quizzes.pose_quiz(view["id"], "Which head now?", "choice", "a", "", ["a", "b"], item=1)).startswith("shown as quiz")
    check = db.blocks(view["id"])[-1]
    assert not db.row("SELECT resolved FROM errors WHERE id = ?", error_id(course))["resolved"]
    asyncio.run(blocks_routes.answer_quiz(check["id"], app.QuizAnswer(answer="a", confidence=0.9)))
    assert db.row("SELECT resolved FROM errors WHERE id = ?", error_id(course))["resolved"]

    assert asyncio.run(lesson_flow.finish_lesson(view["id"], "Head holds now.")) == "finished; end the turn"
    assert recap.revisits_done(course) == 1
    with pytest.raises(HTTPException, match="nothing is left to go over"):
        asyncio.run(sharing_routes.revisit(course))


def error_id(course: int) -> int:
    return db.row("SELECT id FROM errors WHERE course_id = ?", course)["id"]


def test_a_copy_leaves_the_revisits_outline_and_its_open_revisit_still_goes_on(monkeypatch):
    from wise_scholar.tools import lesson_flow, quizzes

    monkeypatch.setattr(app, "_start_turn", lambda *a, **k: None)
    who = _learner()
    course, units = _course(who, [{"title": "Flow", "concepts": ["Head"], "known": []}])
    _finish(course, units["Head"], "2026-10-05 10:00:00")
    _missed(who, course, units["Head"], "2026-10-05 09:00:00")
    asyncio.run(sharing_routes.revisit(course))

    copy = db.copy_course(course, "Flow again")["id"]
    [revisit] = [x["id"] for x in db.rows("SELECT id FROM lessons WHERE course_id = ? AND phase = 'revisit'", copy)]
    assert "Which head?" not in str(db.blocks(revisit)) and '"items"' not in str(db.rows("SELECT data FROM blocks WHERE lesson_id = ?", revisit))
    assert app._lesson_view(revisit)["blocks"] == []
    assert "outline=" not in app._turn_prompt(db.lesson(revisit), "[learner] go on")
    # the tutor cannot give it another one
    assert asyncio.run(lesson_flow.set_outline(revisit, ["a", "b", "c"], cards=9)) == "error: only a unit lesson has an outline"
    assert asyncio.run(quizzes.pose_quiz(revisit, "Which head now?", "choice", "a", "", ["a", "b"], item=1)).startswith("shown as quiz")
    [check] = db.blocks(revisit)
    assert not {"revisit_error", "revisit_claim"} & check["data"].keys()
    asyncio.run(blocks_routes.answer_quiz(check["id"], app.QuizAnswer(answer="a", confidence=0.9)))
    assert not db.row("SELECT resolved FROM errors WHERE id = ?", error_id(course))["resolved"]
    assert asyncio.run(lesson_flow.finish_lesson(revisit, "Head holds now.")) == "finished; end the turn"


def test_a_check_in_a_revisit_whose_outline_names_no_items_is_refused():
    from wise_scholar.tools import quizzes

    course, _ = _course(_learner(), [{"title": "Flow", "concepts": ["Head"], "known": []}])
    revisit = db.create_lesson(course, "Revisit 1", "revisit")
    db.add_block(revisit, "outline", "1. Head", {"steps": ["Head"], "at": 0, "added": None, "cards": 3})
    posed = asyncio.run(quizzes.pose_quiz(revisit, "Which head now?", "choice", "a", "", ["a", "b"], item=1))
    assert posed == "error: in a revisit every check names its item, 1 to 0, as item"


def test_a_revisit_check_on_a_claim_is_evidence_for_it(monkeypatch):
    from wise_scholar.tools import quizzes

    monkeypatch.setattr(app, "_start_turn", lambda *a, **k: None)

    who = _learner()
    course, units = _course(who, [{"title": "Flow", "concepts": ["Head"], "known": []}])
    lesson = _finish(course, units["Head"], "2026-10-05 10:00:00")
    claim = db.record_claims(who, lesson, [{"key": "k", "text": "Head falls with flow.", "evidence": []}], [])["k"]
    revisit = db.create_lesson(course, "Revisit 1", "revisit")
    db.add_block(revisit, "outline", "", recap.revisit_outline([{"kind": "shaky", "id": claim, "text": "Head falls with flow."}]))
    assert asyncio.run(quizzes.pose_quiz(revisit, "Does head rise with flow?", "choice", "no", "", ["yes", "no"], item=1)).startswith("shown as quiz")
    check = db.blocks(revisit)[-1]
    assert db.rows("SELECT claim_id FROM claim_evidence WHERE block_id = ?", check["id"]) == [{"claim_id": claim}]
    assert check["data"]["revisit_claim"] == claim
    asyncio.run(blocks_routes.answer_quiz(check["id"], app.QuizAnswer(answer="no", confidence=0.9)))
    assert db.claim_states(who, NOW)[claim] in ("held", "fading")


def test_a_revisit_rewrites_the_recap_narrative(writer):
    who = _learner()
    course, units = _course(who, [{"title": "Flow", "concepts": ["Head"], "known": []}])
    _finish(course, units["Head"], "2026-10-05 10:00:00")
    asyncio.run(_open(course))
    assert len(writer) == 2
    asyncio.run(_open(course))
    assert len(writer) == 2
    revisit = db.create_lesson(course, "Revisit 1", "revisit")
    db.add_block(revisit, "done", "Done.", {})
    asyncio.run(_open(course))
    assert len(writer) == 4
    assert db.recap(course)["narrative"]["revisits"] == 1


def test_a_revisit_takes_open_mistakes_first_then_shaky_then_fading_claims_up_to_its_size():
    story = {
        "steps": [{"title": "Head", "concept_id": 1}],
        "mistakes": [{"id": 1, "put_right": False, "step": 0}, {"id": 2, "put_right": True, "step": 0}],
        "claims": [{"id": 3, "state": "fading", "step": None}, {"id": 4, "state": "held", "step": 0}]
        + [{"id": 5 + n, "state": "shaky", "step": 0} for n in range(4)],
    }
    items = recap.revisit_items(story)
    assert [(i["kind"], i["id"]) for i in items] == [("mistake", 1), ("shaky", 5), ("shaky", 6), ("shaky", 7)]
    assert items[0]["unit"] == {"title": "Head", "concept_id": 1}
