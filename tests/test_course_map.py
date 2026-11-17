import os
import tempfile

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
