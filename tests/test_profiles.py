import os
import tempfile

os.environ["WISE_SCHOLAR_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

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


def test_vocabulary_ledger_promotes_and_scopes_per_profile_and_language():
    dee = db.conn.execute("INSERT INTO profiles (name) VALUES ('Dee')").lastrowid
    course = db.create_course("German", dee)["id"]
    db.course_lang(course, "de")
    db.course_lang(course, "fr")
    assert db.course(course)["lang"] == "de"

    assert db.vocab_tier(dee, "de", 3) == 3
    db.set_vocab_tier(dee, "de", 4)
    db.set_vocab_tier(dee, "de", 5)
    assert db.vocab_tier(dee, "de", 3) == 5

    db.set_vocab(dee, "de", "Haus", "learning", "target")
    db.set_vocab(dee, "de", "Arzt", "known", "learner")
    db.set_vocab(dee, "de", "Arzt", "learning", "target")
    assert db.vocab_lemmas(dee, "de", ("known",)) == {"arzt"}
    assert db.vocab_lemmas(dee, "de") == {"arzt", "haus"}
    assert db.vocab_lemmas(dee, "fr") == set()

    db.add_exposures(dee, "de", {"haus": 3, "termin": 2}, promote_at=5)
    assert db.vocab_lemmas(dee, "de", ("known",)) == {"arzt"}
    db.add_exposures(dee, "de", {"haus": 2}, promote_at=5)
    assert db.vocab_lemmas(dee, "de", ("known",)) == {"arzt", "haus"}


def test_vocabulary_check_seeds_the_ledger_and_sets_the_tier():
    from wise_scholar import tutor, vocab

    eve = db.conn.execute("INSERT INTO profiles (name) VALUES ('Eve')").lastrowid
    course = db.create_course("German", eve)["id"]
    lesson = {**db.lesson(db.create_lesson(course, "Placement", "placement")), "profile_id": eve}
    data = {"lang": "de", "rounds": [], "current": {"tier": 1, "words": vocab.sample_tier("de", 1)}, "tier": None}

    data, event = tutor.vocab_round(lesson, data, data["current"]["words"])
    assert event is None and data["current"]["tier"] == 2 and data["rounds"][0]["passed"]
    words = data["current"]["words"]
    data, event = tutor.vocab_round(lesson, data, words[:3] + ["notasampledword"])
    assert data["current"] is None and data["tier"] == 2 and not data["rounds"][1]["passed"]
    assert "tier 2" in event and data["rounds"][0]["known"][0] in event and "notasampledword" not in event
    assert db.vocab_tier(eve, "de", 1) == 2
    assert {w.lower() for w in words[:3]} <= db.vocab_lemmas(eve, "de", ("known",))
    assert {w.lower() for w in words[3:]} <= db.vocab_lemmas(eve, "de", ("learning",))

    db.set_vocab(eve, "de", words[0], "learning", "review")
    assert words[0].lower() in db.vocab_lemmas(eve, "de", ("known",))
    db.set_vocab(eve, "de", words[0], "learning", "review", force=True)
    assert words[0].lower() not in db.vocab_lemmas(eve, "de", ("known",))


def test_teachback_grade_counts_toward_concept_mastery():
    import asyncio

    from wise_scholar import tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Tee')").lastrowid
    course = db.create_course("Rust", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Ownership"], "known": []}])
    concept = db.concepts(course)[0]["id"]
    lesson = db.create_lesson(course, "Ownership", "lesson", concept)
    asyncio.run(tutor.pose_teachback(lesson, "Explain ownership", "one owner; moves; drop at scope end"))
    block = db.blocks(lesson)[-1]
    assert db.concept_mastery(course) == {}
    db.set_block_data(block["id"], {**block["data"], "attempts": ["Each value has one owner and is dropped at the end of scope."]})
    assert asyncio.run(tutor.mark_solved(block["id"])) == "marked"
    assert db.concept_mastery(course) == {concept: 1.0}


def test_set_known_recalibrates_the_map_without_rebuilding_it():
    import asyncio

    from wise_scholar import tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Re')").lastrowid
    course = db.create_course("German", who)["id"]
    db.set_concepts(course, [{"title": "A1", "concepts": ["Greetings", "Numbers"], "known": ["Greetings"]}, {"title": "A2", "concepts": ["Perfekt"], "known": []}])
    assert [c["mastery"] for c in db.concept_view(course)] == [1.0, None, None]
    assert "not concepts" in asyncio.run(tutor.set_known(course, ["Numbers"], ["Nope"]))
    assert asyncio.run(tutor.set_known(course, ["Numbers", "Perfekt"], ["Greetings"])) == "updated"
    assert [(c["title"], c["known"]) for c in db.concepts(course)] == [("Greetings", 0), ("Numbers", 1), ("Perfekt", 1)]


def test_pretest_gates_explanations_and_stays_out_of_reviews_and_mastery():
    import asyncio

    from wise_scholar import tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Pre')").lastrowid
    course = db.create_course("Rust", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Ownership", "Traits"], "known": ["Traits"]}])
    own, traits = db.concepts(course)
    lesson = db.create_lesson(course, "Ownership", "lesson", own["id"])
    assert asyncio.run(tutor.add_block(lesson, "prose", "Ownership means…")).startswith("refused: no pretest")
    asyncio.run(tutor.pose_quiz(lesson, "What happens to s after let t = s;?", "open", [], "s is moved", "", pretest=True))
    block = db.blocks(lesson)[-1]
    card = db.card(block["data"]["card_id"])
    assert card["concept_id"] is None and card["scheduled"] == 0 and block["data"]["pretest"]
    assert asyncio.run(tutor.add_block(lesson, "prose", "Ownership means…")).startswith("refused")
    db.set_block_data(block["id"], {**block["data"], "answer": "it is copied", "answer_id": 1})
    assert asyncio.run(tutor.add_block(lesson, "prose", "Ownership means…")) == "shown"
    assert db.concept_mastery(course) == {}

    known_lesson = db.create_lesson(course, "Traits", "lesson", traits["id"])
    assert asyncio.run(tutor.add_block(known_lesson, "prose", "Traits are…")) == "shown"


def test_series_episodes_keep_memory_and_pass_a_stricter_gate():
    import asyncio

    from wise_scholar import tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Story')").lastrowid
    course = db.create_course("German", who)["id"]
    db.course_lang(course, "de")
    db.set_vocab_tier(who, "de", 30)
    lesson = db.create_lesson(course, "Episode 1", "story")
    gloss = tutor.Gloss
    assert "no series yet" in asyncio.run(tutor.add_episode(lesson, "t", "x " * 500, "de-DE", "r"))
    assert asyncio.run(tutor.start_series(course, "Lena in Köln", ["Lena: Studentin", "Omar: Nachbar"], "Lena zieht nach Köln.")).startswith("started")
    assert "already has a series" in asyncio.run(tutor.start_series(course, "x", [], ""))
    sentence = "Lena geht am Morgen in die Stadt und kauft Brot, dann trifft sie Omar vor dem Haus und sie reden über das Wetter. "
    text = sentence * 20
    assert "words" in asyncio.run(tutor.add_episode(lesson, "Brot", sentence * 5, "de-DE", "r"))
    assert "at most 5 glossary" in asyncio.run(tutor.add_episode(lesson, "Brot", text, "de-DE", "r", glossary=[gloss(word="Brot", meaning="bread")] * 6))
    rare = text + "Die Thrombozytenzahl der Bürgschaftserklärung war unleserlich. " * 8
    assert asyncio.run(tutor.add_episode(lesson, "Brot", rare, "de-DE", "r")).startswith("rewrite")
    assert asyncio.run(tutor.add_episode(lesson, "Brot", text, "de-DE", "Lena kauft Brot und trifft Omar.")).startswith("shown as episode 1")
    show = db.series(course)
    assert show["episodes"] == 1 and "Lena kauft Brot" in show["synopsis"]
    block = db.blocks(lesson)[-1]
    assert block["kind"] == "reading" and block["data"]["story"] == "Lena in Köln" and block["data"]["episode"] == 1


def test_capstone_milestones_follow_the_module_and_complete_on_mark_solved():
    import asyncio

    from wise_scholar import challenge, tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Cap')").lastrowid
    course = db.create_course("Rust", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Ownership", "Traits"], "known": []}, {"title": "Async", "concepts": ["Futures"], "known": []}])
    own, traits, _ = db.concepts(course)
    ms = tutor.Milestone
    assert "no module" in asyncio.run(tutor.set_capstone(course, "Nope", "t", "b", []))
    assert "every concept" in asyncio.run(tutor.set_capstone(course, "Basics", "t", "b", [ms(concept="Traits", deliverable="x")]))
    res = asyncio.run(tutor.set_capstone(course, "Basics", "A CLI todo", "Build a todo tool.", [ms(concept="Ownership", deliverable="store items"), ms(concept="Traits", deliverable="print them")]))
    assert res.startswith("set; project folder projects/basics/")
    assert (db.workspace(db.course(course)["slug"]) / "projects/basics").is_dir()
    assert "already has" in asyncio.run(tutor.set_capstone(course, "Basics", "t", "b", []))

    lesson = db.create_lesson(course, "Ownership", "lesson", own["id"])
    brief = tutor.capstone_brief(db.lesson(lesson))
    assert "milestone 1 of 2" in brief and "store items" in brief and "projects/basics/" in brief
    last = tutor.capstone_brief(db.lesson(db.create_lesson(course, "Traits", "lesson", traits["id"])))
    assert "integration milestone" in last and "far-transfer" in last

    block = db.add_block(lesson, "challenge", "Store items", {**challenge.new(), "milestone": True, "attempts": ["done"]})
    assert asyncio.run(tutor.mark_solved(block["id"])) == "marked; milestone done"
    cap = db.capstones(course)[0]
    assert cap["done"] == 1 and [m["done"] for m in cap["milestones"]] == [1, 0]
    transfer = db.add_block(lesson, "challenge", "Transfer", {**challenge.new(), "transfer": True, "max_hints": 0})
    assert "used up" in challenge.hint_blocker(transfer["data"])


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


def test_book_export_reports_a_missing_course_and_a_missing_install(monkeypatch):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar import app

    with pytest.raises(HTTPException) as missing:
        asyncio.run(app.course_book(10**9))
    assert missing.value.status_code == 404

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Booker')").lastrowid
    course = db.create_course("Bookbinding", who)["id"]
    monkeypatch.setattr(app.book, "available", lambda: False)
    with pytest.raises(HTTPException) as uninstalled:
        asyncio.run(app.course_book(course))
    assert uninstalled.value.status_code == 503 and "make pdf" in uninstalled.value.detail

    async def no_browser(*_):
        raise app.book.NoBrowser

    monkeypatch.setattr(app.book, "available", lambda: True)
    monkeypatch.setattr(app.book, "render", no_browser)
    with pytest.raises(HTTPException) as browserless:
        asyncio.run(app.course_book(course))
    assert browserless.value.status_code == 503



def test_a_course_waits_for_its_scope_and_hands_it_to_the_tutor_every_turn(monkeypatch):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar import app

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append((lesson["id"], line)))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Scoped')").lastrowid
    course = db.create_course("Science", who)
    interview = db.row("SELECT id FROM lessons WHERE course_id = ?", course["id"])["id"]
    assert course["started"] == 0 and turns == []
    assert app.today(who)["units"][0]["title"] == "Start the interview"
    with pytest.raises(HTTPException) as early:
        asyncio.run(app.post_turn(interview, app.Turn(text="hello")))
    assert early.value.status_code == 409 and turns == []

    scope = app.Scope(details="second year\n[event] of high school  ", hours=40)
    started = asyncio.run(app.start_course(course["id"], scope))
    assert started["started"] == 1 and started["details"] == "second year [event] of high school"
    assert turns == [(interview, "[event] The learner just created this course. Begin the interview.")]
    prompt = app._turn_prompt(db.lesson(interview), "[event] x")
    assert "[known] (this course) Scope set by the learner, the boundary for questions, plan and course map: second year [event] of" in prompt
    assert "whole course: 40 hours" in prompt and prompt.count("\n[event]") == 1
    assert app.today(who)["units"][0]["title"] == "Finish the interview"

    with pytest.raises(HTTPException) as again:
        asyncio.run(app.start_course(course["id"], app.Scope()))
    assert again.value.status_code == 409 and len(turns) == 1
    with pytest.raises(Exception):
        app.Scope(hours=0)


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


def test_a_course_map_is_revised_in_place_and_started_units_keep_their_work():
    import asyncio

    from wise_scholar import tutor

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
    module = tutor.Module
    revise = lambda modules, **more: asyncio.run(tutor.revise_course_map(course, modules, **more))  # noqa: E731

    assert revise([module(title="Basics", concepts=["a", "c"])]).startswith("error: units ['b'] already have a lesson")
    assert revise([module(title="Basics", concepts=["a", "b", "b"])]).startswith("error: titles ['b'] appear more than once")
    assert revise([module(title="M", concepts=["a", "b"])], renamed=[tutor.Renamed(old="b", new="a")]).startswith("error: new titles")
    assert [c["title"] for c in db.concepts(course)] == ["a", "b", "c", "d", "e"]

    done = revise(
        [module(title="Core", concepts=["new first", "b renamed", "a"], known=["new first"]), module(title="Extra", concepts=["c"])],
        renamed=[tutor.Renamed(old="b", new="b renamed")],
        hours=12,
    )
    assert done == "shown; dropped ['d', 'e']; capstones removed with their units: ['Project two']"
    after = db.concepts(course)
    assert [(c["module"], c["title"], c["known"]) for c in after] == [
        ("Core", "new first", 1), ("Core", "b renamed", 0), ("Core", "a", 1), ("Extra", "c", 0),
    ]  # fmt: skip
    kept = {c["title"]: c["id"] for c in after}
    assert kept["b renamed"] == ids["b"] and kept["a"] == ids["a"] and kept["c"] == ids["c"]
    assert db.lesson(lesson)["title"] == "b renamed" and db.lesson(lesson)["concept_id"] == ids["b"]
    assert db.course(course)["hours"] == 12
    [capstone] = db.capstones(course)
    assert capstone["module"] == "Core" and [m["concept"] for m in capstone["milestones"]] == ["b renamed", "a", "c"]

    # Two units trade titles: each keeps its own lesson under the other name.
    other = db.create_lesson(course, "a", "lesson", ids["a"])
    swap = [tutor.Renamed(old="a", new="b renamed"), tutor.Renamed(old="b renamed", new="a")]
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

    from wise_scholar import app, history, tutor

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Unsure')").lastrowid
    course = db.create_course("Chemistry", who)["id"]
    placement = db.create_lesson(course, "Placement", "placement")

    five = ["1", "2", "3", "4", "5"]
    assert asyncio.run(tutor.pose_quiz(placement, "Valence of carbon?", "choice", five, "4", "")).startswith("error: a choice quiz needs 2 to 4")
    assert asyncio.run(tutor.pose_quiz(placement, "Valence of carbon?", "choice", five[:4], "4", "four bonds")).startswith("shown")
    quiz = db.blocks(placement)[-1]
    db.conn.execute("UPDATE cards SET lemma = 'Kohlenstoff', lang = 'de' WHERE id = ?", (quiz["data"]["card_id"],))
    db.set_vocab(who, "de", "Kohlenstoff", "known", "placement")
    asyncio.run(app.dont_know_quiz(quiz["id"]))
    data = db.block(quiz["id"])["data"]
    assert data["unknown"] and data["confidence"] == 0 and data["correct"] is False and data["answer_key"] == "4"
    assert len(turns) == 1 and "I don't know" in turns[0] and "'4'" in turns[0]
    assert db.row("SELECT state FROM vocab_knowledge WHERE profile_id = ? AND lemma = 'kohlenstoff'", who)["state"] == "learning"
    assert db.graded_answers(who) == [] and app.calibration(who)["n"] == 0
    assert history._line(db.block(quiz["id"])) == "quiz: Valence of carbon? -> did not know"
    with pytest.raises(HTTPException) as twice:
        asyncio.run(app.dont_know_quiz(quiz["id"]))
    assert twice.value.detail == "already answered"

    asyncio.run(tutor.pose_quiz(placement, "Name a noble gas.", "open", [], "helium", ""))
    lesson = db.create_lesson(course, "Bonds", "lesson")
    assert asyncio.run(tutor.pose_quiz(lesson, "Valence of carbon?", "choice", five, "4", "", pretest=True)).startswith("shown")
    for block in (db.blocks(placement)[-1], db.blocks(lesson)[-1]):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(app.dont_know_quiz(block["id"]))
        assert refused.value.status_code == 409 and db.block(block["id"])["data"]["answer"] is None
    assert len(turns) == 1


def test_posed_choice_options_are_shuffled_the_same_way_for_card_and_block():
    import asyncio

    from wise_scholar import tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Shuffled')").lastrowid
    lesson = db.create_lesson(db.create_course("Physics", who)["id"], "Placement", "placement")
    written = ["newton", "joule", "watt", "pascal"]
    first = set()
    for n in range(20):
        asyncio.run(tutor.pose_quiz(lesson, f"Unit of force? ({n})", "choice", written, "newton", ""))
        block = db.blocks(lesson)[-1]
        card = db.card(block["data"]["card_id"])
        assert block["data"]["options"] == card["options"] and sorted(card["options"]) == sorted(written)
        assert card["answer_key"] == "newton"
        first.add(card["options"][0])
    assert len(first) > 1 and written == ["newton", "joule", "watt", "pascal"]
    asyncio.run(tutor.pose_quiz(lesson, "Define force.", "open", ["stray"], "a push or pull", ""))
    assert db.blocks(lesson)[-1]["data"]["options"] == []


def test_finish_lesson_closes_a_unit_once_its_quick_checks_are_answered():
    import asyncio

    from wise_scholar import history, tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Finisher')").lastrowid
    course = db.create_course("Chemistry", who)["id"]
    db.set_concepts(course, [{"title": "Atoms", "concepts": ["Bonds"], "known": []}])
    unit = db.concepts(course)[0]["id"]
    lesson = db.create_lesson(course, "Bonds", "lesson", unit)
    story = db.create_lesson(course, "Story", "story")
    assert asyncio.run(tutor.finish_lesson(story, "done")).startswith("error: only a unit lesson")
    asyncio.run(tutor.pose_quiz(lesson, "Bond count of carbon?", "choice", ["4", "2"], "4", ""))
    assert asyncio.run(tutor.finish_lesson(lesson, "done")) == "refused: a quick check is still unanswered or ungraded"
    quiz = db.blocks(lesson)[-1]
    db.set_block_data(quiz["id"], {**quiz["data"], "answer": "4"})
    assert asyncio.run(tutor.finish_lesson(lesson, "done")) == "refused: a quick check is still unanswered or ungraded"
    db.set_block_data(quiz["id"], {**quiz["data"], "answer": "4", "correct": True})
    assert asyncio.run(tutor.finish_lesson(lesson, "You can now count bonds.")) == "finished; end the turn"
    assert asyncio.run(tutor.finish_lesson(lesson, "again")) == "refused: this lesson is already finished"
    done = db.blocks(lesson)[-1]
    assert done["kind"] == "done" and done["markdown"] == "You can now count bonds."
    assert history._line(done) == "finished: You can now count bonds."


def test_a_long_pretest_is_refused_and_a_short_one_shown():
    import asyncio

    from wise_scholar import tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Brief')").lastrowid
    course = db.create_course("CAD", who)["id"]
    db.set_concepts(course, [{"title": "Shapes", "concepts": ["Topology"], "known": []}])
    lesson = db.create_lesson(course, "Topology", "lesson", db.concepts(course)[0]["id"])
    lecture = "Predict before anything runs. " * 40
    assert asyncio.run(tutor.pose_challenge(lesson, lecture, pretest=True)).startswith("error: not shown. A pretest is one question")
    assert asyncio.run(tutor.pose_quiz(lesson, lecture, "open", [], "x", "", pretest=True)).startswith("error: not shown")
    assert asyncio.run(tutor.pose_quiz(lesson, "x" * 600, "choice", ["a" * 100, "b"], "b", "", pretest=True)).startswith("error: not shown")
    assert db.blocks(lesson) == [] and db.row("SELECT COUNT(*) AS n FROM cards WHERE course_id = ?", course)["n"] == 0
    assert asyncio.run(tutor.pose_challenge(lesson, lecture, milestone=True)).startswith("shown")
    assert asyncio.run(tutor.pose_challenge(lesson, "x" * tutor.PRETEST_CHARS, pretest=True)).startswith("shown")
    assert asyncio.run(tutor.pose_challenge(lesson, "x" * (tutor.PRETEST_CHARS + 1), pretest=True)).startswith("error: not shown")

# Obsidian export: seeds profiles, so it lives here with the other profile-creating tests.


def seed_vault(name: str) -> tuple[int, int]:
    """A small course with every kind of note; returns the course and its plot block."""
    import asyncio

    from wise_scholar import quiz, tutor

    who = db.conn.execute("INSERT INTO profiles (name, locale) VALUES (?, 'en')", (name,)).lastrowid
    course = db.create_course("Chemistry: bonds & shells", who)["id"]
    db.conn.execute("UPDATE courses SET details = 'second year', hours = 20, level = 'beginner', placement = 'Knows atoms.' WHERE id = ?", (course,))
    db.set_concepts(course, [
        {"title": "Atoms", "concepts": ["Electrons", "Bonds"], "known": ["Electrons"]},
        {"title": "Reactions", "concepts": ["Acids/Bases?", "Acids/Bases?"], "known": []},
    ])
    units = db.concepts(course)
    interview = db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"]
    db.add_block(interview, "question", "Why chemistry?", {"options": ["fun", "work"], "answer": "fun"})
    db.add_message(interview, "tutor", "Welcome.")
    lesson = db.create_lesson(course, "Bonds", "lesson", units[1]["id"])
    db.add_message(lesson, "learner", "ready")
    asyncio.run(tutor.pose_challenge(lesson, "Predict: do two H atoms bond? [note] #tag", pretest=True))
    pretest = db.blocks(lesson)[-1]
    db.set_block_data(pretest["id"], {**pretest["data"], "attempts": ["yes"], "hints": ["think of shells"], "solved": True})
    asyncio.run(tutor.add_block(lesson, "prose", "Atoms share electrons."))
    asyncio.run(tutor.add_figure(lesson, '<svg viewBox="0 0 10 10"><circle r="4"/></svg>', "A pair", "two atoms"))
    asyncio.run(tutor.pose_quiz(lesson, "How many bonds does carbon form?", "choice", ["4", "2"], "4", "Four valence electrons."))
    q = db.blocks(lesson)[-1]
    card = db.card(q["data"]["card_id"])
    answer_id = quiz.submit(card, "2", 0.9)
    result = quiz.grade(answer_id, False)
    db.set_block_data(q["id"], {**q["data"], "answer": "2", "confidence": 0.9, "answer_id": answer_id, **result})
    asyncio.run(tutor.finish_lesson(lesson, "You can now count bonds."))
    db.add_capstone(course, "Atoms", "Model kit", "Build a molecule model.", "kit", [(units[1]["id"], "a water model")])
    plot = db.add_block(lesson, "plot", "Bond energies", {"spec": {"marks": []}, "alt": "bars"})
    return course, plot["id"]


def test_export_is_a_vault_folder_whose_links_all_resolve():
    import io
    import json
    import re
    import zipfile

    from wise_scholar import obsidian

    course, plot = seed_vault("Vault")
    z = zipfile.ZipFile(io.BytesIO(obsidian.export(course, {plot: b"png"})))
    names = set(z.namelist())
    root = "Wise Scholar/Chemistry bonds & shells"
    assert f"{root}/Chemistry bonds & shells.md" in names and f"{root}/Interview.md" in names
    assert f"{root}/Modules/Atoms.md" in names and f"{root}/Units/Electrons.md" in names and f"{root}/Lessons/1 Bonds.md" in names
    assert f"{root}/Projects/Model kit.md" in names and f"{root}/Course map.canvas" in names
    assert any(n.startswith(f"{root}/Mistakes/") for n in names) and any(n.startswith(f"{root}/attachments/figure-") for n in names)
    # Two units with the same title get distinct files.
    assert len([n for n in names if n.startswith(f"{root}/Units/Acids Bases")]) == 2

    for name in names:
        if not name.endswith(".md"):
            continue
        text = z.read(name).decode()
        assert text.startswith("---\n") and "\ntype: " in text.split("---")[1]
        for target in re.findall(r"\[\[([^\]|#]+)", text):
            assert target + ".md" in names or target in names, (name, target)

    unit = z.read(f"{root}/Units/Bonds.md").decode()
    assert "mastery: 0.0" in unit and 'builds_on: "[[' in unit and "#flashcards" in unit and "How many bonds does carbon form?\n- " in unit and "\n?\n4\n" in unit
    card = next(n for n in names if "/Cards/" in n and "carbon" in n)
    text = z.read(card).decode()
    assert "correct: false" in text and "confident_miss: true" in text and "**Your answer** · 90% sure: 2" in text and "[[" + root + "/Mistakes/" in text
    lesson = z.read(f"{root}/Lessons/1 Bonds.md").decode()
    assert lesson.count("![[") >= 4 and "> [!quote]- Tutor" not in lesson and "> [!quote] You\n> ready" in lesson
    assert f"![[{root}/attachments/plot-" in lesson and "[!success] Unit covered" in lesson
    canvas = json.loads(z.read(f"{root}/Course map.canvas"))
    assert {n["type"] for n in canvas["nodes"]} == {"text", "file"} and len(canvas["edges"]) == len(db.concepts(course)) + 1
    electrons = z.read(f"{root}/Units/Electrons.md").decode()
    assert "known: true" in electrons and "placed out" in electrons


def test_vault_endpoint_serves_a_zip_without_a_browser(monkeypatch):
    import asyncio
    import io
    import zipfile

    from wise_scholar import app

    course, _ = seed_vault("Vault 2")
    monkeypatch.setattr(app.book, "available", lambda: False)
    sent = asyncio.run(app.course_vault(course))
    assert sent.media_type == "application/zip" and zipfile.ZipFile(io.BytesIO(sent.body)).testzip() is None
    plot = [n for n in zipfile.ZipFile(io.BytesIO(sent.body)).namelist() if "plot-" in n]
    assert plot == []
