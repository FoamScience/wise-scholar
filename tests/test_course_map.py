import os
import tempfile

import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db  # noqa: E402


def test_teachback_grade_counts_toward_concept_mastery():
    import asyncio

    from wise_scholar.tools import practice as practice_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Tee')").lastrowid
    course = db.create_course("Rust", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Ownership"], "known": []}])
    concept = db.concepts(course)[0]["id"]
    lesson = db.create_lesson(course, "Ownership", "lesson", concept)
    asyncio.run(practice_tools.pose_teachback(lesson, "Explain ownership", "one owner; moves; drop at scope end"))
    block = db.blocks(lesson)[-1]
    assert db.concept_mastery(course) == {}
    db.set_block_data(block["id"], {**block["data"], "attempts": ["Each value has one owner and is dropped at the end of scope."]})
    assert asyncio.run(practice_tools.mark_solved(block["id"])) == "marked"
    assert db.concept_mastery(course) == {concept: 1.0}


def test_set_known_recalibrates_the_map_without_rebuilding_it():
    import asyncio

    from wise_scholar.tools import course_plan as plan_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Re')").lastrowid
    course = db.create_course("German", who)["id"]
    db.set_concepts(course, [{"title": "A1", "concepts": ["Greetings", "Numbers"], "known": ["Greetings"]}, {"title": "A2", "concepts": ["Perfekt"], "known": []}])
    assert [c["mastery"] for c in db.concept_view(course)] == [1.0, None, None]
    assert "not concepts" in asyncio.run(plan_tools.set_known(course, ["Numbers"], ["Nope"]))
    assert asyncio.run(plan_tools.set_known(course, ["Numbers", "Perfekt"], ["Greetings"])) == "updated"
    assert [(c["title"], c["known"]) for c in db.concepts(course)] == [("Greetings", 0), ("Numbers", 1), ("Perfekt", 1)]


def test_placement_records_each_area_and_a_retake_replaces_them(monkeypatch):
    import asyncio

    from wise_scholar import app
    from wise_scholar.tools import course_plan as plan_tools
    from wise_scholar.routes import courses as courses_routes

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Placed')").lastrowid
    course = db.create_course("OCCT", who)["id"]
    placement = db.create_lesson(course, "Placement", "placement")
    area = plan_tools.Area
    place = lambda areas: asyncio.run(plan_tools.set_placement(course, "Intermediate", "Knows topology.", areas))  # noqa: E731

    assert place([area(title="Topology", holds="x", lacks="y")]) == "error: give 2 to 8 areas"
    assert "appear more than once" in place([area(title="Topology", holds="", lacks=""), area(title="Topology", holds="", lacks="")])
    assert "too long" in place([area(title="Topology", holds="x" * 301, lacks=""), area(title="Healing", holds="", lacks="")])
    assert place([area(title=" ", holds="", lacks=""), area(title="Healing", holds="", lacks="")]) == "error: every area needs a title"
    assert db.placement_areas(course) == [] and db.course(course)["level"] is None

    first = [area(title="Topology", holds="walks  shapes", lacks=""), area(title="Healing", holds="", lacks="sewing faces")]
    assert place(first) == "recorded"
    assert db.placement_areas(course) == [
        {"title": "Topology", "holds": "walks shapes", "lacks": ""}, {"title": "Healing", "holds": "", "lacks": "sewing faces"},
    ]  # fmt: skip
    assert db.blocks(placement)[-1]["data"]["areas"][1]["lacks"] == "sewing faces"
    prompt = app._turn_prompt(db.lesson(placement), "[event] x")
    assert "[known] (this course) Placement check, by area: Topology: has walks shapes, ends at nothing within the course; Healing: has nothing yet" in prompt
    assert app._course(course)["areas"][0]["title"] == "Topology"
    assert db.placement_areas(db.copy_course(course, "OCCT again")["id"]) == db.placement_areas(course)

    db.set_concepts(course, [{"title": "Basics", "concepts": ["Shapes"], "known": []}])
    lines = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: lines.append(line))
    asyncio.run(courses_routes.retake_placement(course))
    assert "By area: Topology: has walks shapes" in lines[0]
    assert place([area(title="Transforms", holds="", lacks="gp_Trsf"), area(title="Healing", holds="sewing", lacks="")]) == "recorded"
    assert [a["title"] for a in db.placement_areas(course)] == ["Transforms", "Healing"]


def test_units_record_what_they_build_on_and_old_maps_get_it_once(monkeypatch):
    import asyncio

    from wise_scholar import app
    from wise_scholar.tools import course_plan as plan_tools
    from wise_scholar.routes import courses as courses_routes

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Linked')").lastrowid
    course = db.create_course("Impellers", who)["id"]
    module = plan_tools.Module
    make = lambda modules: asyncio.run(plan_tools.set_course_map(course, modules))  # noqa: E731

    assert make([module(title="Blades", concepts=["Camber", "Thickness"], needs={"Thickness": ["Camber", "Hub"]})]).startswith("error: needs names ['Hub']")
    assert make([module(title="Blades", concepts=["Camber", "Thickness"], needs={"Camber": ["Thickness"]})]).startswith("error: a unit needs only units before it")
    assert make([module(title="Blades", concepts=["Camber"]), module(title="Hub", concepts=["Revolve"], needs={"Camber": []})]).startswith("error: needs keys ['Camber']")
    assert db.concepts(course) == []

    assert make([
        module(title="Blades", concepts=["Camber", "Thickness", "Loft"], needs={"Thickness": ["Camber"], "Loft": ["Camber", "Thickness"]}),
        module(title="Hub", concepts=["Revolve", "Fuse"], needs={"Fuse": ["Loft", "Revolve"]}),
    ]) == "shown"  # fmt: skip
    ids = {c["title"]: c["id"] for c in db.concepts(course)}
    assert db.course(course)["prerequisites"] == 1
    view = {c["title"]: c["needs"] for c in db.concept_view(course)}
    assert view["Loft"] == [ids["Camber"], ids["Thickness"]] and view["Fuse"] == [ids["Loft"], ids["Revolve"]] and view["Camber"] == []
    assert "  - Fuse (this lesson; needs Loft, Revolve)" in app._map_outline(course, ids["Fuse"])

    # A revision keeps the edges its new order allows, replaces those it is given, and loses those of dropped units.
    revised = asyncio.run(plan_tools.revise_course_map(course, [
        module(title="Hub", concepts=["Revolve", "Fuse"]),
        module(title="Blades", concepts=["Camber", "Thickness", "Loft 2"], needs={"Loft 2": ["Thickness"]}),
    ], renamed=[plan_tools.Renamed(old="Loft", new="Loft 2")]))  # fmt: skip
    assert revised == "shown"
    view = {c["title"]: c["needs"] for c in db.concept_view(course)}
    assert view["Fuse"] == [ids["Revolve"]] and view["Loft 2"] == [ids["Thickness"]] and view["Thickness"] == [ids["Camber"]]
    copied = db.copy_course(course, "Impellers again")["id"]
    assert sorted(len(c["needs"]) for c in db.concept_view(copied) if c["kind"] == "concept") == [0, 0, 1, 1, 1] and db.course(copied)["prerequisites"] == 1

    # A map from before prerequisites: worked out once in the interview's session, nothing started after that.
    old = db.create_course("Old map", who)["id"]
    db.set_concepts(old, [{"title": "M", "concepts": ["a", "b"], "known": []}])
    started = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, quiet=False: started.append((lesson["phase"], line, quiet)))
    assert asyncio.run(courses_routes.link_map(old)) == {"started": True} and started == [("interview", courses_routes.LINK_MAP + "M:\n  - a (not started)\n  - b (not started)", True)]
    assert asyncio.run(plan_tools.set_prerequisites(old, {"a": ["b"]})).startswith("error: a unit needs only units before it")
    assert asyncio.run(plan_tools.set_prerequisites(old, {"a": []})).startswith("error: no unit needs another")
    assert asyncio.run(plan_tools.set_prerequisites(old, {"b": ["a"]})) == "linked"
    assert db.course(old)["prerequisites"] == 1 and asyncio.run(courses_routes.link_map(old)) == {"started": False}
    assert asyncio.run(courses_routes.link_map(db.create_course("No map", who)["id"])) == {"started": False}
    assert asyncio.run(plan_tools.set_prerequisites(db.create_course("Empty", who)["id"], {"b": ["a"]})) == "error: this course has no map yet; use set_course_map"


def test_a_course_map_is_revised_in_place_and_started_units_keep_their_work():
    import asyncio

    from wise_scholar.tools import course_plan as plan_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Reviser')").lastrowid
    course = db.create_course("Revisable", who)["id"]
    db.set_concepts(course, [
        {"title": "Basics", "concepts": ["a", "b", "c"], "known": ["a"]},
        {"title": "Later", "concepts": ["d", "e"], "known": []},
    ])  # fmt: skip
    ids = {c["title"]: c["id"] for c in db.concepts(course)}
    lesson = db.create_lesson(course, "b", "lesson", ids["b"])
    db.add_capstone(course, "Basics", "Project one", "brief", "p1", [(ids["a"], "x"), (ids["b"], "y"), (ids["c"], "z")])
    db.add_capstone(course, "Later", "Project two", "brief", "p2", [(ids["d"], "x"), (ids["e"], "y")])
    module = plan_tools.Module
    revise = lambda modules, **more: asyncio.run(plan_tools.revise_course_map(course, modules, **more))  # noqa: E731

    assert revise([module(title="Basics", concepts=["a", "c"])]).startswith("error: units ['b'] already have a lesson")
    assert revise([module(title="Basics", concepts=["a", "b", "b"])]).startswith("error: titles ['b'] appear more than once")
    assert revise([module(title="M", concepts=["a", "b"])], renamed=[plan_tools.Renamed(old="b", new="a")]).startswith("error: new titles")
    assert [c["title"] for c in db.concepts(course)] == ["a", "b", "c", "d", "Practice 1", "e"]

    done = revise(
        [module(title="Core", concepts=["new first", "b renamed", "a"], known=["new first"]), module(title="Extra", concepts=["c"])],
        renamed=[plan_tools.Renamed(old="b", new="b renamed")],
        hours=12,
    )
    assert done == "shown; dropped ['d', 'e']; capstones removed with their units: ['Project two']"
    after = db.concepts(course)
    assert [(c["module"], c["title"], c["known"]) for c in after] == [
        ("Core", "new first", 1), ("Core", "b renamed", 0), ("Core", "a", 1), ("Extra", "c", 0),
    ]  # fmt: skip  (two units to study: no practice unit is placed)
    kept = {c["title"]: c["id"] for c in after}
    assert kept["b renamed"] == ids["b"] and kept["a"] == ids["a"] and kept["c"] == ids["c"]
    assert db.lesson(lesson)["title"] == "b renamed" and db.lesson(lesson)["concept_id"] == ids["b"]
    assert db.course(course)["hours"] == 12
    [capstone] = db.capstones(course)
    assert capstone["module"] == "Core" and [m["concept"] for m in capstone["milestones"]] == ["b renamed", "a", "c"]

    # Two units trade titles: each keeps its own lesson under the other name.
    other = db.create_lesson(course, "a", "lesson", ids["a"])
    swap = [plan_tools.Renamed(old="a", new="b renamed"), plan_tools.Renamed(old="b renamed", new="a")]
    assert revise([module(title="Core", concepts=["new first", "a", "b renamed"]), module(title="Extra", concepts=["c"])], renamed=swap) == "shown"
    assert {c["id"]: c["title"] for c in db.concepts(course)}[ids["b"]] == "a" and db.lesson(lesson)["title"] == "a"
    assert db.lesson(other)["title"] == "b renamed"

    for bad, reason in ((0, "hours must be"), (-3, "hours must be"), (10**6, "hours must be")):
        assert reason in revise([module(title="Core", concepts=["new first", "a", "b renamed", "c"])], hours=bad)
    twice = [module(title="Core", concepts=["a"]), module(title="Extra", concepts=["c"]), module(title="Core", concepts=["b renamed", "new first"])]
    assert revise(twice).startswith("error: modules ['Core'] appear more than once")
    assert db.course(course)["hours"] == 12

    # Two capstones end up claiming one module: the one with finished work stays, the other is reported.
    fresh = {c["title"]: c["id"] for c in db.concepts(course)}
    db.add_capstone(course, "Extra", "Project three", "brief", "p3", [(fresh["c"], "w")])
    db.conn.execute("UPDATE milestones SET done = 1 WHERE concept_id = ? AND capstone_id = (SELECT id FROM capstones WHERE title = 'Project three')", (fresh["c"],))
    merged = revise([module(title="All", concepts=["new first", "a", "b renamed", "c"])])
    assert merged == "shown; capstones removed with their units: ['Project one']"
    assert [(k["title"], k["module"]) for k in db.capstones(course)] == [("Project three", "All")]


def test_placement_choice_offers_i_dont_know_as_a_miss_that_stays_out_of_calibration(monkeypatch):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar import app, history, quiz as quiz_module
    from wise_scholar.tools import quizzes as quiz_tools
    from wise_scholar.routes import blocks as blocks_routes, learner as learner_routes

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, then=None: turns.append(line))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Unsure')").lastrowid
    course = db.create_course("Chemistry", who)["id"]
    placement = db.create_lesson(course, "Placement", "placement")

    five = ["1", "2", "3", "4", "5"]
    assert asyncio.run(quiz_tools.pose_quiz(placement, "Valence of carbon?", "choice", "4", "", options=five)).startswith("error: a choice quiz needs 2 to 4")
    assert asyncio.run(quiz_tools.pose_quiz(placement, "Valence of carbon?", "choice", "4", "four bonds", options=five[:4])).startswith("shown")
    quiz = db.blocks(placement)[-1]
    db.conn.execute("UPDATE cards SET lemma = 'Kohlenstoff', lang = 'de' WHERE id = ?", (quiz["data"]["card_id"],))
    db.set_vocab(who, "de", "Kohlenstoff", "known", "placement")
    asyncio.run(blocks_routes.dont_know_quiz(quiz["id"]))
    data = db.block(quiz["id"])["data"]
    assert data["unknown"] and data["confidence"] == 0 and data["correct"] is False and data["answer_key"] == "4"
    assert len(turns) == 1 and "I don't know" in turns[0] and "'4'" in turns[0]
    assert db.row("SELECT state FROM vocab_knowledge WHERE profile_id = ? AND lemma = 'kohlenstoff'", who)["state"] == "learning"
    assert db.graded_answers(who) == [] and learner_routes.calibration(who)["n"] == 0
    assert history._line(db.block(quiz["id"])) == "quiz: Valence of carbon? -> did not know"
    with pytest.raises(HTTPException) as twice:
        asyncio.run(blocks_routes.dont_know_quiz(quiz["id"]))
    assert twice.value.detail == "already answered"

    asyncio.run(quiz_tools.pose_quiz(placement, "Nenne ein Edelgas.", "open", "Helium", "", translation=" Name a noble gas. "))
    translated = db.blocks(placement)[-1]
    assert translated["data"]["translation"] == "Name a noble gas." and "translation" not in quiz["data"]
    assert quiz_module.public(db.card(translated["data"]["card_id"]))["translation"] == "Name a noble gas."
    lesson = db.create_lesson(course, "Bonds", "lesson")
    assert asyncio.run(quiz_tools.pose_quiz(lesson, "Valence of carbon?", "choice", "4", "", pretest=True, options=five)).startswith("shown")
    for block in (db.blocks(placement)[-1], db.blocks(lesson)[-1]):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(blocks_routes.dont_know_quiz(block["id"]))
        assert refused.value.status_code == 409 and db.block(block["id"])["data"]["answer"] is None
    assert len(turns) == 1


def test_placement_length_follows_the_hours_ahead_and_numbers_its_questions(monkeypatch):
    import asyncio

    from wise_scholar import app
    from wise_scholar.tools import quizzes as quiz_tools
    from wise_scholar.routes import courses as courses_routes

    assert [courses_routes.placement_length(h) for h in (None, 0.5, 1, 2, 10, 200, 5000)] == [8, 4, 4, 6, 11, 19, 20]

    lines = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: lines.append(line))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Counted')").lastrowid
    course = db.create_course("Sailing", who)["id"]
    db.conn.execute("UPDATE courses SET hours = 2 WHERE id = ?", (course,))
    db.set_ranking(course, [{"mechanism": "concept-map", "rationale": "x"}])
    placement = asyncio.run(courses_routes.start_placement(course))["id"]
    assert "It has 6 questions, posed in 2 batches of about 3." in lines[-1] and db.lesson(placement)["questions"] == 6
    for n in range(6):
        assert f"placement=question {n} of 6 posed" in app._turn_prompt(db.lesson(placement), "[event] x")
        assert asyncio.run(quiz_tools.pose_quiz(placement, f"Q{n}?", "open", "a", "")).startswith("shown")
        assert {k: db.blocks(placement)[-1]["data"][k] for k in ("number", "of")} == {"number": n + 1, "of": 6}
    assert asyncio.run(quiz_tools.pose_quiz(placement, "Q7?", "open", "a", "")).startswith("error: the placement check has 6 questions")

    db.conn.execute("UPDATE courses SET hours = 200 WHERE id = ?", (course,))
    db.set_concepts(course, [{"title": "Rigging", "concepts": ["Knots", "Sails", "Wind", "Tides"], "known": ["Knots", "Sails"]}])
    monkeypatch.setattr(app, "_require_idle", lambda lesson_id: None)
    retake = asyncio.run(courses_routes.retake_placement(course))["id"]
    assert "About 100 of the course's 200 hours are still ahead." in lines[-1] and "It has 17 questions, posed in 3 batches of about 6." in lines[-1]
    assert db.lesson(retake)["questions"] == 17


def test_a_practice_unit_follows_every_third_unit_and_varies_their_solved_tasks(monkeypatch):
    import asyncio

    from wise_scholar import app, challenge
    from wise_scholar.tools import course_plan as plan_tools, lesson_flow as flow_tools, practice as practice_tools
    from wise_scholar.routes import learner as learner_routes

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append((lesson, line)))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Mixer')").lastrowid
    other_who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Other')").lastrowid
    try:
        course = db.create_course("Algebra", who)["id"]
        other = db.create_course("Elsewhere", other_who)["id"]
        db.set_concepts(other, [{"title": "M", "concepts": ["X"], "known": []}])
        modules = [{"title": "Lines", "concepts": ["Slope", "Intercept", "Parallel", "Perpendicular"], "known": ["Intercept"]},
                   {"title": "Curves", "concepts": ["Parabola", "Vertex", "Roots"], "known": []}]
        db.set_concepts(course, modules)
        titles = [(c["title"], c["kind"], c["module"]) for c in db.concepts(course)]
        assert titles == [("Slope", "concept", "Lines"), ("Intercept", "concept", "Lines"), ("Parallel", "concept", "Lines"), ("Perpendicular", "concept", "Lines"),
                          ("Practice 1", "practice", "Lines"), ("Parabola", "concept", "Curves"), ("Vertex", "concept", "Curves"), ("Roots", "concept", "Curves"),
                          ("Practice 2", "practice", "Curves")]
        by_title = {c["title"]: c for c in db.concepts(course)}
        assert db.started_concepts(course) == set()

        # Two solved tasks in the units before the first practice, one of them a milestone that stays out of it.
        slope = db.create_lesson(course, "Slope", "lesson", by_title["Slope"]["id"])
        parallel = db.create_lesson(course, "Parallel", "lesson", by_title["Parallel"]["id"])
        rise = db.add_block(slope, "challenge", "Slope of the line through (1, 2) and (3, 6)?", {**challenge.new(), "solved": True})
        db.add_block(slope, "challenge", "Milestone", {**challenge.new(), "solved": True, "milestone": True})
        db.add_block(parallel, "challenge", "Unsolved", challenge.new())
        card = db.add_card(course, by_title["Slope"]["id"], "q", "open", [], "a", "", scheduled=True, due="2999-01-01T00:00:00+00:00")
        assert learner_routes.today(who)["units"][0]["title"] == "Slope"

        practice = asyncio.run(learner_routes.open_concept(by_title["Practice 1"]["id"]))
        assert practice["phase"] == "practice" and turns[-1][0]["id"] == practice["id"]
        brief = turns[-1][1]
        assert brief.startswith("[event] The practice begins.") and "Practice 1 (this lesson; practice unit)" in brief
        assert f"- Slope, task {rise['id']}: Slope of the line" in brief and "Milestone" not in brief and "Unsolved" not in brief
        assert "Pose exactly 4 tasks" in brief and practice["cards"] == 5  # one solved task: the fewest, plus the summary
        assert learner_routes._practice_brief(learner_routes._practice_tasks(by_title["Practice 2"]["id"])).startswith("No task of the units before")
        assert learner_routes._practice_size([""] * 9) == 6 and "Pick them from the list" in learner_routes._practice_brief([""] * 9)

        foreign = db.add_block(db.row("SELECT id FROM lessons WHERE course_id = ?", other)["id"], "challenge", "x", {**challenge.new(), "solved": True})
        assert asyncio.run(practice_tools.pose_challenge(practice["id"], "v", variant_of=foreign["id"])).startswith("error: variant_of")
        assert asyncio.run(practice_tools.pose_challenge(practice["id"], "v", variant_of=10**9)).startswith("error: variant_of")
        unsolved = db.blocks(parallel)[-1]
        assert asyncio.run(practice_tools.pose_challenge(practice["id"], "v", variant_of=unsolved["id"])).startswith("error: variant_of")
        assert asyncio.run(practice_tools.pose_challenge(slope, "v", variant_of=rise["id"])) == "error: variant_of is for the tasks of a practice unit"
        assert asyncio.run(practice_tools.pose_challenge(practice["id"], "Slope through (2, 1) and (4, 7)?", variant_of=rise["id"])).startswith("shown")
        variant = db.blocks(practice["id"])[-1]
        assert variant["data"]["variant_of"] == rise["id"]
        assert asyncio.run(practice_tools.pose_challenge(practice["id"], "again", variant_of=rise["id"])).startswith("error: task")
        assert f"task {rise['id']}" not in learner_routes._practice_brief(learner_routes._practice_tasks(by_title["Practice 1"]["id"]))  # varied once: not offered again

        # Revealed unsolved: the unit's cards come forward and the notebook gets the miss.
        db.set_block_data(variant["id"], {**variant["data"], "attempts": ["1"], "gave_up": True, "hints": ["Rise over run."]})
        assert asyncio.run(practice_tools.reveal(variant["id"], "3")) == "shown"
        assert db.card(card)["due"] < "2999"
        entry = db.errors(who)[-1]
        assert entry["kind"] == "practice" and entry["said"] == "1" and entry["correct"] == "3" and entry["explanation"] == ""

        assert asyncio.run(flow_tools.finish_lesson(practice["id"], "Done.")) == "finished; end the turn"
        view = {c["title"]: c["mastery"] for c in db.concept_view(course)}
        assert view["Practice 1"] == 1.0 and view["Practice 2"] is None
        assert learner_routes.today(who)["units"][0]["title"] == "Slope"

        # A revision keeps the practice unit that has a lesson and lays the rest out again.
        revised = asyncio.run(plan_tools.revise_course_map(course, [plan_tools.Module(title="Lines", concepts=["Slope", "Parallel"]), plan_tools.Module(title="Curves", concepts=["Parabola"])], hours=None))
        assert revised.startswith("shown")
        after = [(c["title"], c["kind"], c["module"]) for c in db.concepts(course)]
        assert after == [("Slope", "concept", "Lines"), ("Parallel", "concept", "Lines"), ("Parabola", "concept", "Curves"), ("Practice 1", "practice", "Curves")]
        assert db.lesson(practice["id"])["title"] == "Practice 1"
        assert asyncio.run(plan_tools.revise_course_map(course, [plan_tools.Module(title="Lines", concepts=["Slope", "Parallel", "Practice 1"])])).startswith("error: ['Practice 1'] are practice units")
        assert asyncio.run(plan_tools.set_known(course, ["Practice 1"], [])).startswith("error: ['Practice 1'] are not concepts")
        # Placing a unit out moves the practice unit: with one unit left to study, none is placed by the rule, the kept one closes the map.
        assert asyncio.run(plan_tools.set_known(course, ["Slope", "Parabola"], [])) == "updated"
        assert [c["title"] for c in db.concepts(course)] == ["Slope", "Parallel", "Parabola", "Practice 1"]
        assert "no module" not in asyncio.run(plan_tools.set_capstone(course, "Curves", "Graph it", "b", [plan_tools.Milestone(concept="Parabola", deliverable="plot")]))
    finally:
        db.delete_course(course)
        db.delete_course(other)
        db.conn.execute("DELETE FROM profiles WHERE id IN (?, ?)", (who, other_who))


@pytest.fixture
def imported(monkeypatch, tmp_path):
    """Makes a replay of a course whose author finished the first concept unit, with one task in it, for another
    profile, from the units (title and kind) of each version published; the replay is moved through all of them.
    finished: the practice units the author finished too; before_upgrade: called with the replay before each move."""
    import asyncio
    import io
    import uuid

    from fastapi import UploadFile

    from wise_scholar import app, challenge
    from wise_scholar.routes import sharing as sharing_routes

    for module, name in ((db, "WORKSPACE"), (app, "SOURCES"), (app, "VERSIONS")):
        monkeypatch.setattr(module, name, tmp_path / name.lower())
    last = db.row("SELECT COALESCE(MAX(id), 0) AS n FROM profiles")["n"]

    def make(*maps: list[tuple[str, str]], finished: tuple[str, ...] = (), before_upgrade=lambda replay: None) -> int:
        author, reader = (
            db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"{who} {uuid.uuid4().hex[:6]}",)).lastrowid
            for who in ("Scope author", "Scope reader")
        )
        course, mine, ids = db.create_course("Ratios", author)["id"], None, {}
        for units in maps:
            for n, (title, kind) in enumerate(units, start=1):
                if title in ids:
                    db.conn.execute("UPDATE concepts SET position = ? WHERE id = ?", (n, ids[title]))
                else:
                    ids[title] = db.conn.execute(
                        "INSERT INTO concepts (course_id, module, title, known, position, kind) VALUES (?, 'Parts', ?, 0, ?, ?)", (course, title, n, kind),
                    ).lastrowid
            if mine is None:
                first = next(title for title, kind in units if kind == "concept")
                lesson = db.create_lesson(course, first, "lesson", ids[first])
                db.add_block(lesson, "challenge", "Split 12 in the ratio 1 to 2.", challenge.new())
                db.add_block(lesson, "done", "", {})
                for title in finished:
                    db.add_block(db.create_lesson(course, title, "practice", ids[title]), "done", "", {})
            version = sharing_routes.publish_version(course, sharing_routes.Publish())["hash"]
            if mine is None:
                with open(sharing_routes.version_bundle(version).path, "rb") as f:
                    mine = asyncio.run(sharing_routes.import_course(reader, UploadFile(io.BytesIO(f.read()), filename="ratios.zip")))["id"]
            else:
                before_upgrade(mine)
                sharing_routes.upgrade_course(mine, sharing_routes.Upgrade(hash=version))
        assert (db.course(mine)["mode"], db.course(mine)["profile_id"]) == ("replay", reader)
        assert [c["position"] for c in db.concepts(mine)] == list(range(len(maps[-1])))
        return mine

    yield make
    for c in db.rows("SELECT id FROM courses WHERE profile_id > ?", last):
        db.delete_course(c["id"])
    db.conn.execute("DELETE FROM versions")
    db.conn.execute("DELETE FROM profiles WHERE id > ?", (last,))


def _solve_imported(course: int) -> dict:
    """The replay's one task, tried by its reader and marked solved by the tutor."""
    import asyncio

    from wise_scholar.tools import practice as practice_tools

    [task] = [b for lesson in db.rows("SELECT id FROM lessons WHERE course_id = ?", course) for b in db.blocks(lesson["id"]) if b["kind"] == "challenge"]
    db.set_block_data(task["id"], {**task["data"], "attempts": ["4 and 8"]})
    assert asyncio.run(practice_tools.mark_solved(task["id"])) == "marked"
    return db.block(task["id"])


def _scopes(course: int) -> dict[str, list[str]]:
    return {c["title"]: [u["title"] for u in db.practice_scope(c["id"])] for c in db.concepts(course) if c["kind"] == "practice"}


REPLAYED_MAP = [("Parts", "concept"), ("Wholes", "concept"), ("Practice 1", "practice"), ("Scales", "concept"), ("Practice 2", "practice")]


def test_the_first_unit_of_an_imported_course_is_in_its_practice_units_scope(imported):
    course = imported(REPLAYED_MAP)
    assert _scopes(course) == {"Practice 1": ["Parts", "Wholes"], "Practice 2": ["Scales"]}


def test_a_solved_task_of_an_imported_courses_first_unit_is_offered(monkeypatch, imported):
    import asyncio

    from wise_scholar import app
    from wise_scholar.routes import learner as learner_routes

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    course = imported(REPLAYED_MAP)
    task = _solve_imported(course)
    unit = next(c for c in db.concepts(course) if c["title"] == "Practice 1")
    practice = asyncio.run(learner_routes.open_concept(unit["id"]))
    assert practice["phase"] == "practice"
    assert f"- Parts, task {task['id']}: Split 12" in turns[-1]


def test_a_variant_of_an_imported_courses_first_unit_is_posed(imported):
    import asyncio

    from wise_scholar.tools import practice as practice_tools

    course = imported(REPLAYED_MAP)
    task = _solve_imported(course)
    unit = next(c for c in db.concepts(course) if c["title"] == "Practice 1")
    practice = db.create_lesson(course, "Practice 1", "practice", unit["id"])
    assert asyncio.run(practice_tools.pose_challenge(practice, "Split 20 in the ratio 1 to 4.", variant_of=task["id"])).startswith("shown")
    assert db.blocks(practice)[-1]["data"]["variant_of"] == task["id"]


def test_an_upgrade_that_puts_a_unit_first_puts_it_in_the_practice_units_scope(imported):
    course = imported(REPLAYED_MAP, [("Pieces", "concept"), *REPLAYED_MAP])
    assert _scopes(course) == {"Practice 1": ["Pieces", "Parts", "Wholes"], "Practice 2": ["Scales"]}


def test_a_practice_unit_that_opens_an_imported_course_covers_nothing_and_the_next_one_what_follows_it(imported):
    course = imported([("Warm-up", "practice"), ("Parts", "concept"), ("Wholes", "concept"), ("Practice 1", "practice")])
    assert _scopes(course) == {"Warm-up": [], "Practice 1": ["Parts", "Wholes"]}


MARKED_MAP = [("Parts", "concept"), ("Wholes", "concept"), ("Practice 1", "practice"),
              ("Scales", "concept"), ("Rates", "concept"), ("Mixing it up", "practice")]


def _mark(course: int, known: list[str], unknown: list[str] = []) -> None:
    import asyncio

    from wise_scholar.tools import course_plan as plan_tools

    assert asyncio.run(plan_tools.set_known(course, known, unknown)) == "updated"


def _placed(course: int) -> list[dict]:
    """The units of a map as its version gave them, with their lessons."""
    return [{k: c[k] for k in ("id", "key", "title", "module", "kind", "position", "unwritten")} | {
        "lessons": db.rows("SELECT id, title FROM lessons WHERE concept_id = ?", c["id"]),
    } for c in db.concepts(course)]


@pytest.mark.parametrize("mark", [
    lambda c: _mark(c, []),
    lambda c: _mark(c, ["Parts"]),
    lambda c: _mark(c, ["Scales", "Rates"]),
    lambda c: _mark(c, ["Parts", "Wholes", "Scales", "Rates"]),
    lambda c: (_mark(c, ["Parts", "Scales"]), _mark(c, ["Rates"], ["Parts", "Scales"])),
], ids=["none", "one", "a practice's", "all", "and back"])
def test_marking_units_known_leaves_an_imported_courses_units_as_they_came(imported, mark):
    course = imported(MARKED_MAP, finished=("Practice 1",))
    before, scopes = _placed(course), _scopes(course)
    assert [u["lessons"] != [] for u in before] == [True, False, True, False, False, False]
    mark(course)
    assert _placed(course) == before
    assert _scopes(course) == scopes == {"Practice 1": ["Parts", "Wholes"], "Mixing it up": ["Scales", "Rates"]}


def test_an_upgrade_after_a_mark_keeps_the_practice_units_and_the_readers_work_in_them(imported):
    seen = {}

    def mark(course: int) -> None:
        unit = next(c for c in db.concepts(course) if c["title"] == "Mixing it up")
        seen["lesson"] = db.create_lesson(course, unit["title"], "practice", unit["id"])
        seen["block"] = db.add_block(seen["lesson"], "challenge", "Mix them.", {"attempts": ["2 to 3"]})["id"]
        _mark(course, ["Parts", "Scales", "Rates"])
        seen["before"] = _placed(course)

    course = imported(MARKED_MAP, [*MARKED_MAP, ("Percent", "concept")], finished=("Practice 1",), before_upgrade=mark)
    assert _placed(course)[:-1] == seen["before"]
    assert db.block(seen["block"])["data"]["attempts"] == ["2 to 3"]
    assert [(c["title"], c["known"]) for c in db.concepts(course)] == [
        ("Parts", 1), ("Wholes", 0), ("Practice 1", 0), ("Scales", 1), ("Rates", 1), ("Mixing it up", 0), ("Percent", 0),
    ]


def test_an_upgrade_gives_back_the_practice_units_a_mark_took_before(imported):
    """db.place_practice is what a mark did to an imported course: it dropped and moved its practice units."""
    lost = []

    def drop(course: int) -> None:
        db.place_practice(course)
        lost.extend(c["title"] for c in db.concepts(course))

    course = imported(MARKED_MAP, [*MARKED_MAP, ("Percent", "concept")], finished=("Practice 1",), before_upgrade=drop)
    assert lost == ["Parts", "Wholes", "Scales", "Practice 1", "Rates"]
    assert [c["title"] for c in db.concepts(course)] == [*(title for title, _ in MARKED_MAP), "Percent"]
    assert _scopes(course) == {"Practice 1": ["Parts", "Wholes"], "Mixing it up": ["Scales", "Rates"]}


def _revised(course: int, modules: dict[str, list[str]], renamed: dict[str, str] = {}) -> list[tuple[str, str]]:
    import asyncio

    from wise_scholar.tools import course_plan as plan_tools

    assert asyncio.run(plan_tools.revise_course_map(
        course, [plan_tools.Module(title=m, concepts=units) for m, units in modules.items()],
        [plan_tools.Renamed(old=old, new=new) for old, new in renamed.items()],
    )).startswith("shown")
    assert [c["position"] for c in db.concepts(course)] == list(range(1, len(db.concepts(course)) + 1))
    return [(c["module"], c["title"]) for c in db.concepts(course)]


def test_revising_an_imported_courses_map_keeps_each_practice_unit_after_the_units_it_covers(imported):
    course = imported(MARKED_MAP, finished=("Practice 1",))
    keys = {c["key"] for c in db.concepts(course) if c["kind"] == "practice"}
    as_it_came = [("Parts", title) for title, _ in MARKED_MAP]
    assert _revised(course, {"Parts": ["Parts", "Wholes", "Scales", "Rates"]}) == as_it_came
    assert _revised(course, {"Parts": ["Scales", "Rates", "Wholes", "Parts"]}) == [
        ("Parts", t) for t in ("Scales", "Rates", "Mixing it up", "Wholes", "Parts", "Practice 1")]
    assert _revised(course, {"Parts": ["Parts", "Wholes"], "Change": ["Scales", "Rates of change", "Rates of flow"]}, {"Rates": "Rates of change"}) == [
        ("Parts", "Parts"), ("Parts", "Wholes"), ("Parts", "Practice 1"),
        ("Change", "Scales"), ("Change", "Rates of change"), ("Change", "Rates of flow"), ("Change", "Mixing it up")]
    assert {c["key"] for c in db.concepts(course) if c["kind"] == "practice"} == keys


def test_a_new_unit_in_the_next_module_is_not_covered_by_the_imported_practice_unit_before_it(imported):
    course = imported(MARKED_MAP)
    assert _revised(course, {"Parts": ["Parts", "Wholes"], "Change": ["Speeds", "Scales", "Rates"]}) == [
        ("Parts", "Parts"), ("Parts", "Wholes"), ("Parts", "Practice 1"),
        ("Change", "Speeds"), ("Change", "Scales"), ("Change", "Rates"), ("Change", "Mixing it up")]


def test_a_revision_that_leaves_out_what_an_imported_practice_unit_covers_leaves_it_out_unless_it_was_written(imported):
    course = imported([*MARKED_MAP, ("Percent", "concept"), ("Practice 3", "practice")], finished=("Practice 3",))
    assert _revised(course, {"Parts": ["Parts", "Wholes"]}) == [("Parts", t) for t in ("Parts", "Wholes", "Practice 1", "Practice 3")]


def test_an_imported_practice_unit_in_a_module_of_its_own_stays_in_it(imported):
    course = imported(MARKED_MAP)
    db.conn.execute("UPDATE concepts SET module = 'Review' WHERE course_id = ? AND title = 'Mixing it up'", (course,))
    assert _revised(course, {"Parts": ["Parts", "Wholes"], "Change": ["Scales", "Rates"]})[2:] == [
        ("Parts", "Practice 1"), ("Change", "Scales"), ("Change", "Rates"), ("Review", "Mixing it up")]


def test_an_upgrade_after_a_revision_lays_the_new_version_out_and_keeps_the_practice_units(imported):
    seen = {}

    def revise(course: int) -> None:
        unit = next(c for c in db.concepts(course) if c["title"] == "Mixing it up")
        seen["lesson"] = db.create_lesson(course, unit["title"], "practice", unit["id"])
        seen["block"] = db.add_block(seen["lesson"], "challenge", "Mix them.", {"attempts": ["2 to 3"]})["id"]
        seen["before"] = _placed(course)
        _revised(course, {"Change": ["Scales", "Rates of change", "Rates of flow"], "Parts": ["Wholes", "Parts"]}, {"Rates": "Rates of change"})

    course = imported([*MARKED_MAP, ("Percent", "concept"), ("Wrap-up", "practice")], [*MARKED_MAP, ("Percent", "concept"), ("Wrap-up", "practice"), ("Powers", "concept")],
                      finished=("Practice 1",), before_upgrade=revise)
    # Percent and Wrap-up, which the revision left out, are back as new rows; the split-off unit is gone.
    after = _placed(course)
    assert after[:6] == seen["before"][:6]
    assert [(u["key"], u["title"], u["kind"]) for u in after[6:8]] == [(u["key"], u["title"], u["kind"]) for u in seen["before"][6:]]
    assert [u["title"] for u in after[8:]] == ["Powers"]
    assert db.block(seen["block"])["data"]["attempts"] == ["2 to 3"]


def test_an_ordinary_courses_marks_and_revisions_lay_its_practice_units_out_by_the_rule():
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Rule keeper')").lastrowid
    course = db.create_course("Kept by the rule", who)["id"]
    units = lambda: [(c["position"], c["module"], c["title"], c["known"]) for c in db.concepts(course)]  # noqa: E731
    try:
        db.set_concepts(course, [{"title": "M", "concepts": ["A", "B", "C", "D"], "known": []}, {"title": "N", "concepts": ["E", "F", "G"], "known": []}])
        _, second = (c["id"] for c in db.concepts(course) if c["kind"] == "practice")
        lesson = db.create_lesson(course, "Practice 2", "practice", second)
        db.set_known(course, ["A", "B"], [])
        assert units() == [(1, "M", "A", 1), (2, "M", "B", 1), (3, "M", "C", 0), (4, "M", "D", 0), (5, "N", "E", 0), (6, "N", "Practice 1", 0),
                           (7, "N", "F", 0), (8, "N", "G", 0)]
        assert [c["id"] for c in db.concepts(course) if c["kind"] == "practice"] == [second] and db.lesson(lesson)["title"] == "Practice 1"
        db.set_known(course, [], ["A", "B"])
        assert units() == [(1, "M", "A", 0), (2, "M", "B", 0), (3, "M", "C", 0), (4, "M", "Practice 1", 0), (5, "M", "D", 0), (6, "N", "E", 0),
                           (7, "N", "F", 0), (8, "N", "Practice 2", 0), (9, "N", "G", 0)]
        db.revise_concepts(course, [{"title": "N", "concepts": ["E", "F", "H"], "known": []}, {"title": "M", "concepts": ["A", "D"], "known": ["D"]}], {})
        assert units() == [(1, "N", "E", 0), (2, "N", "F", 0), (3, "N", "H", 0), (4, "N", "Practice 1", 0), (5, "M", "A", 0), (6, "M", "D", 1)]
        assert [c["id"] for c in db.concepts(course) if c["kind"] == "practice"] == [second]
    finally:
        db.delete_course(course)


def test_a_course_made_by_its_map_has_the_scopes_it_had():
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Scope mapper')").lastrowid
    course = db.create_course("Made by its map", who)["id"]
    try:
        db.set_concepts(course, [{"title": "M", "concepts": ["A", "B", "C", "D", "E", "F"], "known": []}])
        assert [c["position"] for c in db.concepts(course)] == [1, 2, 3, 4, 5, 6, 7, 8]
        assert _scopes(course) == {"Practice 1": ["A", "B", "C"], "Practice 2": ["D", "E", "F"]}
    finally:
        db.delete_course(course)


def test_the_course_map_counts_each_units_due_reviews():
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Mapper')").lastrowid
    course = db.create_course("Elixir", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Pipes", "Pattern matching"], "known": []}])
    pipes, matching = (c["id"] for c in db.concepts(course) if c["kind"] == "concept")
    for due in ("2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00", "2999-01-01T00:00:00+00:00"):
        db.add_card(course, pipes, "q", "open", [], "a", "e", scheduled=True, due=due)
    view = {c["id"]: c for c in db.concept_view(course)}
    assert view[pipes]["due"] == 2 and view[matching]["due"] == 0


def test_the_course_map_fits_the_hours_at_the_time_the_learner_takes_per_unit():
    import asyncio

    from wise_scholar import app
    from wise_scholar.tools import course_plan as plan_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Timed')").lastrowid
    course = db.create_course("Throughflow", who)["id"]
    db.conn.execute("UPDATE courses SET hours = 2 WHERE id = ?", (course,))
    assert asyncio.run(plan_tools.set_sitting(course, 2)) == "error: a sitting is 5 to 240 minutes"
    assert asyncio.run(plan_tools.set_sitting(course, 30)) == "sitting set to 30 minutes"
    # Unmeasured, a unit runs twice the sitting: 2 hours fit two units, and a third is refused unless placed out.
    assert plan_tools.unit_minutes(db.course(course)) == (60, 0) and plan_tools.map_budget(db.course(course)) == 2
    three = [plan_tools.Module(title="Loops", concepts=["Balance", "Momentum", "Solver"])]
    refused = asyncio.run(plan_tools.set_course_map(course, three))
    assert refused.startswith("error: the map has 3 units to study; at about 60 minutes a unit") and "fit 2" in refused
    assert asyncio.run(plan_tools.set_course_map(course, [plan_tools.Module(title="Loops", concepts=["Balance", "Momentum", "Solver"], known=["Balance"])])) == "shown"
    assert asyncio.run(plan_tools.revise_course_map(course, [plan_tools.Module(title="Loops", concepts=["Balance", "Momentum", "Solver", "Slip"])])).startswith("error: the map has 3")
    assert asyncio.run(plan_tools.revise_course_map(course, [plan_tools.Module(title="Loops", concepts=["Balance", "Momentum", "Solver", "Slip"])], hours=4)) == "shown"
    # A practice unit counts against the hours too: four hours of hour-long units hold three units to study.
    assert plan_tools.map_budget(db.course(course), 4) == 3

    # Finished units measure the learner: active time with the time away cut out, per unit and per task.
    units = [c for c in db.concepts(course) if c["kind"] == "concept"]
    for n, unit in enumerate(units[:2]):
        lesson = db.create_lesson(course, unit["title"], "lesson", unit["id"])
        for at in ("10:00", "10:10", "10:20", "11:40"):
            db.conn.execute("INSERT INTO messages (lesson_id, role, text, created) VALUES (?, 'learner', 'x', ?)", (lesson, f"2026-01-0{n + 1} {at}:00"))
        db.add_block(lesson, "challenge", "Do it.", {})
        db.add_block(lesson, "done", "Done.", {})
        db.conn.execute("UPDATE blocks SET created = ? WHERE lesson_id = ?", (f"2026-01-0{n + 1} 10:20:00", lesson))
    assert db.unit_pace(who) == {"units": 2, "unit": 20, "task": 20}
    assert plan_tools.map_budget(db.course(course)) == 9
    # A long tutor turn the learner waited on counts, though no event fell inside it; a background turn does not.
    used = {"model": "m", "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": None}
    db.add_usage(course, lesson, "lesson", "claude", used, 40 * 60)
    db.add_usage(course, lesson, "graph", "claude", used, 50 * 60)
    db.conn.execute("UPDATE usage SET created = '2026-01-02 11:40:00' WHERE lesson_id = ?", (lesson,))
    assert db.unit_pace(who) == {"units": 2, "unit": 40, "task": 40}
    state = app._turn_prompt(db.lesson(lesson), "x")
    assert " sitting=30 min task=40 min" in state
    assert "A unit takes this learner about 40 minutes (measured over their last 2 units), so the map holds at most 5 units" in state


def test_a_lesson_begins_with_the_course_playbook_in_its_event(monkeypatch):
    import asyncio

    from wise_scholar import app
    from wise_scholar.routes import learner as learner_routes

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Playbook')").lastrowid
    course = db.create_course("Optics", who)["id"]
    try:
        db.set_concepts(course, [{"title": "Light", "concepts": ["Refraction"], "known": []}])
        db.conn.execute("UPDATE courses SET mechanism = 'worked-examples' WHERE id = ?", (course,))
        asyncio.run(learner_routes.open_concept(db.concepts(course)[0]["id"]))
        assert turns[-1].startswith("[event] The lesson begins.") and "\n[playbook worked-examples] " in turns[-1]
        assert app._playbook_line(None) == "" and app._playbook_line("nonsense") == ""
    finally:
        db.delete_course(course)


def test_a_placement_batch_reaches_the_tutor_once_every_card_is_answered(monkeypatch):
    from wise_scholar import app
    from wise_scholar.routes import blocks as block_routes, courses as courses_routes

    turns = []
    started = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, then=None: (turns.append(line), started.append(then)))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Placement batcher')").lastrowid
    course = db.create_course("Statics", who)["id"]
    try:
        placement = db.lesson(db.create_lesson(course, "Placement", "placement", questions=6))
        first = db.add_block(placement["id"], "quiz", "q1", {"card_id": 0, "kind": "choice", "options": [], "answer": None})
        second = db.add_block(placement["id"], "quiz", "q2", {"card_id": 0, "kind": "choice", "options": [], "answer": None})
        db.set_block_data(first["id"], {**first["data"], "answer": "a"})
        block_routes._quiz_turn(placement, first["id"], "[event] Quiz 1 result: correct")
        assert turns == []
        db.set_block_data(second["id"], {**second["data"], "answer": "b"})
        block_routes._quiz_turn(placement, second["id"], "[event] Quiz 2 result: wrong")
        assert turns == ["[event] Quiz 1 result: correct\n\n[event] Quiz 2 result: wrong"]
        # the turn failed: the batch waits for the next turn, and goes once a turn carrying it ends well
        assert app._held_answers(placement["id"])[0] == turns[0]
        started[-1]()
        assert app._held_answers(placement["id"])[0] == ""
        assert all("unheard" not in b["data"] for b in db.blocks(placement["id"]))

        lesson = db.lesson(db.create_lesson(course, "Unit", "lesson"))
        block_routes._quiz_turn(lesson, db.add_block(lesson["id"], "quiz", "q", {"answer": "a"})["id"], "[event] one")
        assert turns[-1] == "[event] one"
        assert courses_routes._batches(6) == ", posed in 2 batches of about 3"
        assert courses_routes._batches(14) == ", posed in 3 batches of about 5"
    finally:
        db.delete_course(course)
