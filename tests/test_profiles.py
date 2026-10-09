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
    assert asyncio.run(tutor.add_block(lesson, "prose", "Ownership means…")).startswith("refused: the lesson has no attempted opening")
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


def test_an_exercise_with_a_run_counts_as_the_lesson_opening(monkeypatch):
    import asyncio

    from wise_scholar import sandbox, tutor

    monkeypatch.setattr(sandbox, "commands", lambda: True)
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Opener')").lastrowid
    course = db.create_course("Shell", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Pipes"], "known": []}])
    lesson = db.create_lesson(course, "Pipes", "lesson", db.concepts(course)[0]["id"])
    assert asyncio.run(tutor.add_block(lesson, "prose", "A pipe joins…")).startswith("refused")
    assert asyncio.run(tutor.pose_exercise(lesson, "Run it", [tutor.ExerciseFile(path="p/x.sh", content="echo hi | wc -c")], "sh p/x.sh")).startswith("shown")
    assert asyncio.run(tutor.add_block(lesson, "prose", "A pipe joins…")).startswith("refused")
    block = db.blocks(lesson)[-1]
    db.set_block_data(block["id"], {**block["data"], "last_run": {"exit_code": 0, "output": "3\n"}})
    assert asyncio.run(tutor.add_block(lesson, "prose", "A pipe joins…")) == "shown"


def test_vault_folder_is_kept_current_and_never_touches_the_learners_own_notes(tmp_path):
    import json

    from wise_scholar import obsidian, vault

    course, _ = seed_vault("Vault 3")
    folder = vault.write(course, tmp_path)
    manifest = json.loads((folder / vault.MANIFEST).read_text())
    assert folder == tmp_path / obsidian.Vault(course).root and all((tmp_path / p).exists() for p in manifest)
    own = folder / "My notes.md"
    own.write_text("[[Units/Bonds]] matters")
    unit = next(p for p in manifest if "/Units/Bonds" in p)
    lesson = db.rows("SELECT id FROM lessons WHERE course_id = ? ORDER BY id DESC", course)[0]["id"]
    db.add_block(lesson, "prose", "Later addition.", {})
    db.conn.execute("UPDATE concepts SET title = 'Covalent bonds' WHERE course_id = ? AND title = 'Bonds'", (course,))
    vault.write(course, tmp_path)
    after = json.loads((folder / vault.MANIFEST).read_text())
    assert not (tmp_path / unit).exists() and any("/Units/Covalent bonds" in p for p in after)
    assert "Later addition." in (tmp_path / next(p for p in after if "/Lessons/" in p)).read_text()
    assert own.read_text() == "[[Units/Bonds]] matters"
    # A renamed course moves to a new folder and leaves none behind.
    db.conn.execute("UPDATE courses SET topic = 'Chemistry renamed' WHERE id = ?", (course,))
    moved = vault.write(course, tmp_path)
    assert moved != folder and not (folder / vault.MANIFEST).exists() and not (folder / "Units").exists() and own.exists()
    vault.remove(course, tmp_path)
    assert own.exists() and not (moved / vault.MANIFEST).exists() and not (moved / "Units").exists()


def test_vault_follows_published_changes_from_any_thread(tmp_path, monkeypatch):
    import asyncio
    import threading

    from wise_scholar import hub, obsidian, vault

    course, _ = seed_vault("Vault 4")
    monkeypatch.setattr(vault, "VAULT", tmp_path)
    monkeypatch.setattr(vault, "SETTLE", 0.2)
    monkeypatch.setattr(hub, "_listeners", [])
    lesson = db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"]

    async def scenario():
        await vault.start()
        for i in range(3):
            db.add_block(lesson, "prose", f"change {i}", {})
            threading.Thread(target=hub.publish, args=(course, {"type": "block.added"})).start()
            await asyncio.sleep(0.05)
        for _ in range(50):
            await asyncio.sleep(0.1)
            note = tmp_path / obsidian.Vault(course).root / "Interview.md"
            if note.exists() and "change 2" in note.read_text() and not vault._pending:
                return True
        return False

    assert asyncio.run(scenario())


def test_two_courses_with_one_title_get_two_vault_folders():
    from wise_scholar import obsidian

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Twin')").lastrowid
    first = db.create_course("Chemistry: bonds & shells", who)["id"]
    second = db.create_course("chemistry bonds & shells", who)["id"]
    assert obsidian.Vault(first).root != obsidian.Vault(second).root and obsidian.Vault(second).root.endswith(f"({second})")


def test_a_material_url_is_fetched_through_checked_hops_and_private_addresses_are_refused(monkeypatch):
    import asyncio
    import functools

    import httpx
    import pytest
    from fastapi import HTTPException

    from wise_scholar import app

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
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"x" * (app.SOURCE_LIMIT + 1))
        if request.url.path == "/loop":
            return httpx.Response(302, headers={"location": "https://example.org/loop"})
        return httpx.Response(404)

    # The real check, on addresses that need no DNS: this machine and a private range are refused, a public one passes.
    for private in ("127.0.0.1", "localhost", "10.0.0.1", "169.254.169.254"):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(app._public_address(private, []))
        assert refused.value.status_code == 422, private
    assert asyncio.run(app._public_address("93.184.216.34", [])) == "93.184.216.34"
    with pytest.raises(HTTPException):
        asyncio.run(app._public_address("::1", []))

    async def public(host, networks):
        return "203.0.113.9"

    monkeypatch.setattr(app, "_public_address", public)
    monkeypatch.setattr(app.httpx, "AsyncClient", functools.partial(httpx.AsyncClient, transport=httpx.MockTransport(serve)))

    source = asyncio.run(app.fetch_source(course, app.SourceUrl(url="https://github.example.org/raw/peepcode-git")))
    assert source["name"] == "peepcode.pdf" and source["size"] == 13
    # Each hop is sent to the checked address, with the name kept for the Host header and the certificate.
    assert hops == ["https://203.0.113.9/raw/peepcode-git", "https://203.0.113.9/peepcode"]
    assert any(p.name == f"{source['id']}-peepcode.pdf" for p in (app.SOURCES / str(course)).iterdir())
    page = asyncio.run(app.fetch_source(course, app.SourceUrl(url="https://example.org/page.cgi")))
    assert page["name"] == "page.html"
    for bad, status, detail in (("http://example.org:8321/api/profiles", 422, "only public"), ("ftp://example.org/x.pdf", 422, "http://"),
                                ("https://example.org/loop", 422, "too many"), ("https://example.org/missing", 422, "did not answer"),
                                ("https://example.org/big.pdf", 413, "50 MB"), ("not a url", 422, "http://")):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(app.fetch_source(course, app.SourceUrl(url=bad)))
        assert refused.value.status_code == status and detail in refused.value.detail, bad
    prompt = app._turn_prompt(db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"]), "[event] x")
    assert "peepcode.pdf (still being read)" in prompt
    db.finish_source(source["id"], [("page 1", "Git stores snapshots.")])
    prompt = app._turn_prompt(db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"]), "[event] x")
    assert "Materials the learner gave for this course, to plan and teach from: peepcode.pdf (1 sections)" in prompt


def test_a_teacher_profile_prepares_courses_with_the_designer_prompts_and_no_learner_gates(monkeypatch):  # noqa: C901
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar import app, tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Ms Teach')").lastrowid
    assert db.profile(who)["mode"] == "learner"
    assert app.set_mode(who, app.ProfileMode(mode="teacher"))["mode"] == "teacher"
    course = db.create_course("Chemistry for year 10", who)
    assert course["mode"] == "teacher"
    interview = db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ?", course["id"])["id"])
    assert app._phase_prompt(interview) == "interview-teacher"
    for name in ("interview-teacher", "lesson-teacher"):
        assert (db.ROOT / "wise_scholar" / "prompts" / f"{name}.md").exists()

    db.set_concepts(course["id"], [{"title": "Atoms", "concepts": ["Bonds"], "known": []}])
    lesson = db.create_lesson(course["id"], "Bonds", "lesson", db.concepts(course["id"])[0]["id"])
    assert app._phase_prompt(db.lesson(lesson)) == "lesson-teacher"
    # No opening gate, no pretest length cap, immediate solutions, unscheduled quizzes, finish without answers.
    assert asyncio.run(tutor.add_block(lesson, "prose", "Objectives…")) == "shown"
    assert asyncio.run(tutor.pose_challenge(lesson, "Predict. " * 120, pretest=True, form="prediction")).startswith("shown")
    opening = db.blocks(lesson)[-1]
    assert asyncio.run(tutor.give_hint(opening["id"], "Think of shells.")).startswith("shown as hint 1")
    assert asyncio.run(tutor.reveal(opening["id"], "Two bonds.")) == "shown"
    assert asyncio.run(tutor.pose_quiz(lesson, "Valence of carbon?", "choice", ["4", "2"], "4", "Four electrons.")).startswith("shown")
    assert db.card(db.blocks(lesson)[-1]["data"]["card_id"])["scheduled"] == 0
    assert asyncio.run(tutor.finish_lesson(lesson, "Plan done.")) == "finished; end the turn"
    with pytest.raises(HTTPException) as refused:
        asyncio.run(app.start_placement(course["id"]))
    assert refused.value.status_code == 409 and "prepared course" in refused.value.detail
    # Nobody answers an authored card through the API either.
    for call in (lambda: app.answer_quiz(db.blocks(lesson)[-2]["id"], app.QuizAnswer(answer="4", confidence=0.5)),
                 lambda: app.attempt(opening["id"], app.Answer(answer="x"))):
        with pytest.raises(HTTPException) as closed:
            asyncio.run(call())
        assert closed.value.status_code == 409 and "take no answers" in closed.value.detail

    # A learner's course keeps its gates and its placement flow, retake included.
    learner = db.conn.execute("INSERT INTO profiles (name) VALUES ('Still learning')").lastrowid
    plain = db.create_course("Chemistry", learner)["id"]
    assert db.course(plain)["mode"] == "learner" and app._phase_prompt(db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ?", plain)["id"])) == "interview"
    db.set_concepts(plain, [{"title": "Atoms", "concepts": ["Bonds"], "known": []}])
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: None)
    retake = asyncio.run(app.retake_placement(plain))
    assert retake["phase"] == "placement"


def test_handouts_give_the_teacher_the_solutions_and_the_students_the_tasks(monkeypatch):
    import asyncio

    from wise_scholar import app, handout, tutor

    who = db.conn.execute("INSERT INTO profiles (name, mode) VALUES ('Handout', 'teacher')").lastrowid
    course = db.create_course("Chemistry handouts", who)["id"]
    db.set_concepts(course, [{"title": "Atoms", "concepts": ["Bonds"], "known": []}])
    lesson = db.create_lesson(course, "Bonds", "lesson", db.concepts(course)[0]["id"])
    asyncio.run(tutor.add_block(lesson, "prose", "## Objectives\n\nCount bonds."))
    asyncio.run(tutor.pose_challenge(lesson, "How many bonds does carbon form?", pretest=True, form="prediction"))
    opening = db.blocks(lesson)[-1]
    asyncio.run(tutor.give_hint(opening["id"], "Count valence electrons."))
    asyncio.run(tutor.reveal(opening["id"], "Four."))
    asyncio.run(tutor.pose_quiz(lesson, "Which is a noble gas?", "choice", ["Helium", "Oxygen"], "Helium", "Full outer shell."))
    asyncio.run(tutor.add_figure(lesson, '<svg viewBox="0 0 10 10"><circle r="4"/></svg>', "A pair", "two atoms"))

    from wise_scholar import sandbox

    monkeypatch.setattr(sandbox, "COMMANDS", True)
    asyncio.run(tutor.pose_exercise(lesson, "Count the bonds in water.", [tutor.ExerciseFile(path="w/count.py", content="print(2)")], "uv run w/count.py"))
    exercise = db.blocks(lesson)[-1]
    db.set_block_data(exercise["id"], {**exercise["data"], "last_run": {"exit_code": 0, "output": "2\n"}, "solution": "Two bonds."})
    teacher = handout.markdown(lesson, solutions=True)
    student = handout.markdown(lesson, solutions=False)
    assert teacher.startswith("# Bonds\n\nChemistry handouts\n") and "## Objectives" in teacher and "data:image/svg+xml;base64," in teacher
    assert "Count valence electrons." in teacher and "Four." in teacher and "**Helium**" in teacher and "Full outer shell." in teacher
    assert "How many bonds does carbon form?" in student and "Which is a noble gas?" in student and "- Helium" in student
    for secret in ("Count valence electrons.", "Four.", "**Helium**", "Full outer shell.", "## Objectives", "Two bonds.", "exit 0", "[["):
        assert secret not in student, secret
    assert "Count the bonds in water." in student and "`w/count.py`" in student and "data:image/svg+xml;base64," in student
    assert "**Solution**\n>" in teacher and "[!solution]" not in teacher and "Two bonds." in teacher
    sent = app.lesson_handout(lesson, "student")
    assert sent.media_type.startswith("text/markdown") and sent.body.decode() == student
    assert app.get_lesson(lesson)["course_id"] == course


def test_a_prepared_course_is_duplicated_with_its_plan_and_without_its_record(tmp_path, monkeypatch):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar import app, tutor

    monkeypatch.setattr(app, "SOURCES", tmp_path / "sources")
    monkeypatch.setattr(db, "WORKSPACE", tmp_path / "workspace")
    who = db.conn.execute("INSERT INTO profiles (name, mode) VALUES ('Copier', 'teacher')").lastrowid
    course = db.create_course("Chemistry to copy", who)["id"]
    db.conn.execute("UPDATE courses SET details = 'year 10', hours = 20, mechanism = 'concept-map' WHERE id = ?", (course,))
    db.set_concepts(course, [{"title": "Atoms", "concepts": ["Bonds", "Shells"], "known": []}])
    bonds, shells = db.concepts(course)
    db.add_capstone(course, "Atoms", "Model kit", "Build a model.", "kit", [(shells["id"], "a water model")])
    lesson = db.create_lesson(course, "Bonds", "lesson", bonds["id"])
    asyncio.run(tutor.pose_quiz(lesson, "Valence of carbon?", "choice", ["4", "2"], "4", "Four."))
    asyncio.run(tutor.pose_challenge(lesson, "Predict the bond.", pretest=True, form="prediction"))
    trial = db.blocks(lesson)[-1]
    db.set_block_data(trial["id"], {**trial["data"], "attempts": ["my trial"], "solved": True, "solution": "Covalent."})
    failed = db.add_source(course, "broken.pdf", 5)
    db.finish_source(failed["id"], [], "no text could be read from the file")
    db.add_message(lesson, "learner", "make it shorter")
    db.add_fact(course, "class of 28", False)
    source = db.add_source(course, "syllabus.md", 10)
    db.finish_source(source["id"], [("part 1", "Atoms first.")])
    (tmp_path / "sources" / str(course)).mkdir(parents=True)
    (tmp_path / "sources" / str(course) / f"{source['id']}-syllabus.md").write_text("Atoms first.")
    (db.workspace(db.course(course)["slug"]) / "demo.py").write_text("print(1)")

    copy = app.duplicate_course(course)
    assert copy["topic"] == "Chemistry to copy (2)" and copy["mode"] == "teacher" and copy["id"] != course
    assert app.duplicate_course(copy["id"])["topic"] == "Chemistry to copy (3)"
    # The material comes along, the work done on the original does not.
    copied_trial = db.blocks(db.rows("SELECT id FROM lessons WHERE course_id = ? AND concept_id IS NOT NULL", copy["id"])[0]["id"])[-1]
    assert copied_trial["data"]["solution"] == "Covalent." and copied_trial["data"]["attempts"] == [] and copied_trial["data"]["solved"] is False
    assert db.blocks(lesson)[-1]["data"]["attempts"] == ["my trial"]
    new = db.course(copy["id"])
    assert (new["details"], new["hours"], new["mechanism"]) == ("year 10", 20, "concept-map")
    assert [c["title"] for c in db.concepts(copy["id"])] == ["Bonds", "Shells"]
    assert db.capstones(copy["id"])[0]["milestones"][0]["concept"] == "Shells" and db.capstones(copy["id"])[0]["done"] == 0
    lessons = db.rows("SELECT * FROM lessons WHERE course_id = ? ORDER BY id", copy["id"])
    assert [l["phase"] for l in lessons] == ["interview", "lesson"] and all(l["session_started"] == 0 for l in lessons)
    quiz = next(b for b in db.blocks(lessons[1]["id"]) if b["kind"] == "quiz")
    card = db.card(quiz["data"]["card_id"])
    assert card["course_id"] == copy["id"] and card["concept_id"] == db.concepts(copy["id"])[0]["id"] and card["answer_key"] == "4"
    assert db.rows("SELECT text FROM messages WHERE lesson_id = ?", lessons[1]["id"])[0]["text"] == "make it shorter"
    assert [f["text"] for f in db.facts(copy["id"])] == ["class of 28"]
    copied_source = db.sources(copy["id"])[0]
    assert len(db.sources(copy["id"])) == 1 and copied_source["status"] == "ready" and db.search_sources(copy["id"], "Atoms", 1)[0]["title"].endswith("part 1")
    assert db.search_sources(course, "Atoms", 2)[0]["title"].endswith("part 1") and len(db.sources(course)) == 2
    assert (tmp_path / "sources" / str(copy["id"]) / f"{copied_source['id']}-syllabus.md").read_text() == "Atoms first."
    assert (db.workspace(new["slug"]) / "demo.py").read_text() == "print(1)"
    assert db.commands(who) == [] and db.graded_answers(who) == []
    learner = db.conn.execute("INSERT INTO profiles (name) VALUES ('No copy')").lastrowid
    with pytest.raises(HTTPException) as refused:
        app.duplicate_course(db.create_course("Mine", learner)["id"])
    assert refused.value.status_code == 409


def test_a_teacher_edits_removes_and_reorders_the_cards_of_a_plan():
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar import app, tutor

    who = db.conn.execute("INSERT INTO profiles (name, mode) VALUES ('Editor', 'teacher')").lastrowid
    course = db.create_course("Chemistry edits", who)["id"]
    db.set_concepts(course, [{"title": "Atoms", "concepts": ["Bonds"], "known": []}])
    lesson = db.create_lesson(course, "Bonds", "lesson", db.concepts(course)[0]["id"])
    asyncio.run(tutor.add_block(lesson, "prose", "## Objectives\n\nCount bonds."))
    asyncio.run(tutor.pose_challenge(lesson, "How many bonds?", pretest=True, form="prediction"))
    asyncio.run(tutor.pose_quiz(lesson, "Noble gas?", "choice", ["Helium", "Oxygen"], "Helium", "Full shell."))
    prose, task, quiz = db.blocks(lesson)

    edited = app.edit_block(task["id"], app.BlockEdit(markdown="How many bonds does carbon form?", solution="Four.", hints=["Count electrons.", " ", "Think shells."]))
    assert edited["markdown"] == "How many bonds does carbon form?" and edited["data"]["solution"] == "Four." and edited["data"]["hints"] == ["Count electrons.", "Think shells."]
    with pytest.raises(HTTPException) as bad:
        app.edit_block(quiz["id"], app.BlockEdit(options=["Helium", "Neon"], answer_key="Argon"))
    assert bad.value.status_code == 422
    edited = app.edit_block(quiz["id"], app.BlockEdit(markdown="Which is a noble gas?", options=["Helium", "Neon", "Oxygen"], answer_key="Neon", explanation="Also full."))
    card = db.card(quiz["data"]["card_id"])
    assert (card["question"], card["options"], card["answer_key"], card["explanation"]) == ("Which is a noble gas?", ["Helium", "Neon", "Oxygen"], "Neon", "Also full.")
    assert edited["data"]["answer_key"] == "Neon" and edited["data"]["options"] == ["Helium", "Neon", "Oxygen"]

    order = app.move_block(quiz["id"], app.Move(direction="up"))
    assert [b["id"] for b in order] == [prose["id"], quiz["id"], task["id"]]
    order = app.move_block(prose["id"], app.Move(direction="up"))
    assert [b["id"] for b in order] == [prose["id"], quiz["id"], task["id"]]  # already first
    app.remove_block(quiz["id"])
    assert [b["id"] for b in db.blocks(lesson)] == [prose["id"], task["id"]] and db.card(card["id"]) is None

    learner = db.conn.execute("INSERT INTO profiles (name) VALUES ('Reader only')").lastrowid
    plain = db.create_course("Chemistry plain", learner)["id"]
    plain_lesson = db.row("SELECT id FROM lessons WHERE course_id = ?", plain)["id"]
    block = db.add_block(plain_lesson, "prose", "Hello", {})
    with pytest.raises(HTTPException) as refused:
        app.edit_block(block["id"], app.BlockEdit(markdown="Changed"))
    assert refused.value.status_code == 409


def test_a_question_card_may_take_several_answers():
    import asyncio

    from wise_scholar import app, tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Many')").lastrowid
    course = db.create_course("Statistics", who)["id"]
    interview = db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"]
    assert asyncio.run(tutor.ask(interview, "What do you already use?", ["Excel"])).startswith("error: a question card takes")
    assert asyncio.run(tutor.ask(interview, "What do you already use?", ["Excel", "Python", "R"], multiple=True)).startswith("shown")
    block = db.blocks(interview)[-1]
    assert block["data"]["multiple"] is True and block["data"]["answer"] is None
    turns = []
    app_turn = app._start_turn
    app._start_turn = lambda lesson, line: turns.append(line)
    try:
        asyncio.run(app.answer_question(block["id"], app.Answer(answer="Excel; R")))
    finally:
        app._start_turn = app_turn
    assert db.block(block["id"])["data"]["answer"] == "Excel; R" and "Excel; R" in turns[0]


def test_sketch_is_a_profile_choice_on_by_default():
    from wise_scholar import app

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Sketcher')").lastrowid
    assert db.profile(who)["sketch"] is True
    assert app.set_sketch(who, app.ProfileSketch(sketch=False))["sketch"] is False
    assert next(p for p in db.profiles() if p["id"] == who)["sketch"] is False


def test_redraw_sends_the_tutor_back_to_each_figure_and_replace_figure_keeps_the_block(monkeypatch, tmp_path):
    import asyncio
    import json

    import pytest
    from fastapi import HTTPException

    from wise_scholar import app, art, tutor

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Redraw')").lastrowid
    course = db.create_course("Cells", who)["id"]
    db.conn.execute("UPDATE courses SET started = 1 WHERE id = ?", (course,))
    lesson = db.create_lesson(course, "The cell", "lesson", None)
    monkeypatch.setattr(art, "ART", tmp_path)
    art._manifests.clear()
    with pytest.raises(HTTPException, match="the lesson has no figures"):
        asyncio.run(app.redraw_figures(lesson))
    asyncio.run(tutor.add_block(lesson, "prose", "A cell."))
    asyncio.run(tutor.add_figure(lesson, '<svg viewBox="0 0 10 10"><circle r="4"/></svg>', "A cell", "a circle"))
    asyncio.run(tutor.add_figure(lesson, '<svg viewBox="0 0 10 10"><rect width="4" height="4"/></svg>', "A box", "a square"))
    first, second = [b for b in db.blocks(lesson) if b["kind"] == "figure"]
    assert first["data"]["credits"] == []
    with pytest.raises(HTTPException, match="no art pack is installed"):
        asyncio.run(app.redraw_figures(lesson))

    (tmp_path / "bioicons" / "cc-0" / "Cell_types" / "Me").mkdir(parents=True)
    (tmp_path / "bioicons" / "cc-0" / "Cell_types" / "Me" / "cell.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 1"><path d="M0 0h1"/></svg>')
    (tmp_path / "bioicons" / "manifest.json").write_text(json.dumps([{"id": "bioicons/cc-0/Cell_types/Me/cell", "name": "cell", "category": "Cell types", "author": "Me", "licence": "CC0", "ratio": 2.0}]))
    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    assert asyncio.run(app.redraw_figures(lesson)) == {"figures": [first["id"], second["id"]]}
    assert turns[0].startswith(f"[redraw] Draw figures {first['id']}, {second['id']} of this lesson again, one replace_figure call each")
    assert "find_art" in app._turn_prompt(db.lesson(lesson), turns[0]) and "Art pack installed: Bioicons (1 icons; Cell types)" in app._turn_prompt(db.lesson(lesson), turns[0])

    assert asyncio.run(tutor.find_art("cell")) == "bioicons/cc-0/Cell_types/Me/cell | cell | Cell types | Me | CC0 | 2.0"
    assert asyncio.run(tutor.find_art("zebra")).startswith("nothing found")
    redrawn = asyncio.run(
        tutor.replace_figure(lesson, first["id"], '<svg viewBox="0 0 10 10"><use href="art:bioicons/cc-0/Cell_types/Me/cell" width="4" height="2"/></svg>', "A real cell", "an icon of a cell")
    )
    assert redrawn == f"figure {first['id']} redrawn"
    block = db.block(first["id"])
    assert block["markdown"] == "A real cell" and block["position"] == first["position"] and [b["id"] for b in db.blocks(lesson)][1:] == [first["id"], second["id"]]
    assert f'<symbol id="f{first["id"]}-art-1" viewBox="0 0 2 1">' in block["data"]["svg"] and f'href="#f{first["id"]}-art-1"' in block["data"]["svg"]
    assert block["data"]["credits"] == [{"name": "cell", "author": "Me", "licence": "CC0", "pack": "Bioicons", "url": "https://bioicons.com"}]
    assert block["data"]["previous"] == {**first["data"], "caption": "A cell"} and "restored" not in block["data"]
    with pytest.raises(HTTPException, match="nothing to restore"):
        app.restore_figure(second["id"])
    with pytest.raises(HTTPException, match="no such figure"):
        app.restore_figure(10**9)
    back = app.restore_figure(first["id"])
    assert back["markdown"] == "A cell" and back["data"]["svg"] == first["data"]["svg"] and back["data"]["restored"] is True
    assert back["data"]["previous"]["caption"] == "A real cell" and "art-1" in back["data"]["previous"]["svg"] and "previous" not in back["data"]["previous"]
    again = app.restore_figure(first["id"])
    assert again["markdown"] == "A real cell" and again["data"]["restored"] is False and again["data"]["previous"] == {**first["data"], "caption": "A cell"}
    assert (asyncio.run(tutor.replace_figure(lesson, second["id"], '<svg viewBox="0 0 1 1"><use href="art:bioicons/x"/></svg>', "c", "a"))).startswith("error: no art with id")
    assert asyncio.run(tutor.replace_figure(lesson, 10**9, "<svg/>", "c", "a")) == "error: no figure with id 1000000000 in this lesson"
    other = db.create_lesson(course, "Elsewhere", "lesson", None)
    assert asyncio.run(tutor.replace_figure(other, first["id"], "<svg/>", "c", "a")) == f"error: no figure with id {first['id']} in this lesson"
    assert asyncio.run(tutor.add_figure(lesson, "<svg viewBox='0 0 1 1'/>", "c", "")) == "error: alt text is required"

    from wise_scholar import obsidian

    assert obsidian._credits(block["data"]["credits"]) == "*Art: cell (Me, CC0) · [Bioicons](https://bioicons.com)*\n"
    assert obsidian._credits([]) == ""
    assert obsidian._credits([{"name": "a*b", "author": "[x](y)", "licence": "CC0", "pack": "P_", "url": "u"}]) == "*Art: a\\*b (\\[x\\]\\(y\\), CC0) · [P\\_](u)*\n"
    note = obsidian.Vault(course).lesson_text(db.lesson(lesson) | {"blocks": db.blocks(lesson), "messages": []}, chat=False, kinds=("figure",))
    assert "".join(note).count("*Art: cell (Me, CC0)") == 1
    redrawn_twice = asyncio.run(tutor.replace_figure(lesson, first["id"], '<svg viewBox="0 0 1 1"><rect width="1" height="1"/></svg>', "Third", "a square"))
    assert redrawn_twice == f"figure {first['id']} redrawn"
    third = db.block(first["id"])
    assert third["data"]["previous"]["caption"] == "A real cell" and "restored" not in third["data"] and "previous" not in third["data"]["previous"]
