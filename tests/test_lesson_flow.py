import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db  # noqa: E402


def test_finish_lesson_closes_a_unit_once_its_quick_checks_are_answered():
    import asyncio

    from wise_scholar import history
    from wise_scholar.tools import lesson_flow as flow_tools, quizzes as quiz_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Finisher')").lastrowid
    course = db.create_course("Chemistry", who)["id"]
    db.set_concepts(course, [{"title": "Atoms", "concepts": ["Bonds"], "known": []}])
    unit = db.concepts(course)[0]["id"]
    lesson = db.create_lesson(course, "Bonds", "lesson", unit)
    story = db.create_lesson(course, "Story", "story")
    assert asyncio.run(flow_tools.finish_lesson(story, "done")).startswith("error: only a unit lesson")
    asyncio.run(quiz_tools.pose_quiz(lesson, "Bond count of carbon?", "choice", "4", "", options=["4", "2"]))
    assert asyncio.run(flow_tools.finish_lesson(lesson, "done")) == "refused: a quick check is still unanswered or ungraded"
    quiz = db.blocks(lesson)[-1]
    db.set_block_data(quiz["id"], {**quiz["data"], "answer": "4"})
    assert asyncio.run(flow_tools.finish_lesson(lesson, "done")) == "refused: a quick check is still unanswered or ungraded"
    db.set_block_data(quiz["id"], {**quiz["data"], "answer": "4", "correct": True})
    assert asyncio.run(flow_tools.finish_lesson(lesson, "You can now count bonds.")) == "finished; end the turn"
    assert asyncio.run(flow_tools.finish_lesson(lesson, "again")) == "refused: this lesson is already finished"
    done = db.blocks(lesson)[-1]
    assert done["kind"] == "done" and done["markdown"] == "You can now count bonds."
    assert history._line(done) == "finished: You can now count bonds."


def test_an_exercise_with_a_run_counts_as_the_lesson_opening(monkeypatch):
    import asyncio

    from wise_scholar import sandbox
    from wise_scholar.tools import lesson_flow as flow_tools, practice as practice_tools

    monkeypatch.setattr(sandbox, "commands", lambda: True)
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Opener')").lastrowid
    course = db.create_course("Shell", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Pipes"], "known": []}])
    lesson = db.create_lesson(course, "Pipes", "lesson", db.concepts(course)[0]["id"])
    assert asyncio.run(flow_tools.add_block(lesson, "prose", "A pipe joins…")).startswith("refused")
    assert asyncio.run(practice_tools.pose_exercise(lesson, "Run it", [practice_tools.ExerciseFile(path="p/x.sh", content="echo hi | wc -c")], "sh p/x.sh")).startswith("shown")
    assert asyncio.run(flow_tools.add_block(lesson, "prose", "A pipe joins…")).startswith("refused")
    block = db.blocks(lesson)[-1]
    db.set_block_data(block["id"], {**block["data"], "last_run": {"exit_code": 0, "output": "3\n"}})
    assert asyncio.run(flow_tools.add_block(lesson, "prose", "A pipe joins…")) == "shown"


def test_a_batch_lesson_carries_its_keys_and_takes_its_answers_together(monkeypatch):
    import asyncio
    import json

    import pytest
    from fastapi import HTTPException

    from wise_scholar import app, tutor
    from wise_scholar.tools import quizzes as quiz_tools
    from wise_scholar.routes import lessons as lessons_routes

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Batcher')").lastrowid
    course = db.create_course("Chemistry", who)["id"]
    db.set_concepts(course, [{"title": "Bonds", "concepts": ["Ionic bonds"], "known": []}])
    lesson = db.create_lesson(course, "Ionic bonds", "lesson", db.concepts(course)[0]["id"])
    with pytest.raises(HTTPException, match="not prepared for offline"):
        asyncio.run(lessons_routes.send_batch(lesson, lessons_routes.Batch(answers=[])))
    placement = db.create_lesson(course, "Placement", "placement", None)
    with pytest.raises(HTTPException, match="only a unit of a learner's course"):
        asyncio.run(lessons_routes.prepare_offline(placement))
    done = db.create_lesson(course, "Done", "lesson", db.concepts(course)[0]["id"])
    db.add_block(done, "done", "Finished.", None)
    with pytest.raises(HTTPException, match="this lesson is finished"):
        asyncio.run(lessons_routes.prepare_offline(done))
    db.conn.execute("UPDATE courses SET mode = 'teacher' WHERE id = ?", (course,))
    with pytest.raises(HTTPException, match="only a unit of a learner's course"):
        asyncio.run(lessons_routes.prepare_offline(lesson))
    db.conn.execute("UPDATE courses SET mode = 'learner' WHERE id = ?", (course,))

    asyncio.run(lessons_routes.prepare_offline(lesson))
    assert turns[-1].startswith("[batch] The learner takes this unit offline") and app._lesson_view(lesson)["batch"] == 1
    with pytest.raises(HTTPException, match="already prepared"):
        asyncio.run(lessons_routes.prepare_offline(lesson))
    # No opening attempt gates the explanations: the whole unit is written in one turn.
    assert tutor.pretest_blocker(db.lesson(lesson)) is None
    posed = asyncio.run(quiz_tools.pose_quiz(lesson, "Which gives electrons away?", "choice", "Na", "Metals lose electrons.", pretest=True, options=["Na", "Cl"]))
    assert posed.endswith("; go on with the unit")
    asyncio.run(quiz_tools.pose_quiz(lesson, "Why does NaCl conduct when molten?", "open", "Its ions move freely.", "Charge moves with the ions."))
    item = lambda text, category: quiz_tools.SortItem(text=text, category=category)  # noqa: E731
    items = [item("NaCl", "ionic"), item("KBr", "ionic"), item("MgO", "ionic"), item("H2O", "covalent"), item("CH4", "covalent"), item("CO2", "covalent")]
    asyncio.run(quiz_tools.pose_sort(lesson, "Ionic or covalent?", ["ionic", "covalent"], items, "A metal and a non-metal bond ionically."))
    asyncio.run(quiz_tools.pose_quiz(lesson, "Which ion is larger?", "choice", "Cl-", "Extra electrons spread the cloud.", options=["Na+", "Cl-"]))
    pretest, open_, sort, skipped = db.blocks(lesson)
    assert pretest["data"]["answer_key"] == "Na" and open_["data"]["explanation"] == "Charge moves with the ions."
    assert all(o["category"] for o in sort["data"]["options"])  # the device grades the sort itself

    given = lambda block_id, answer, **more: lessons_routes.BatchAnswer(block_id=block_id, answer=answer, confidence=0.9, **more)  # noqa: E731
    placed = json.dumps({o["text"]: o["category"] for o in sort["data"]["options"]} | {"CO2": "ionic"})
    with pytest.raises(HTTPException, match="the learner's own grade"):
        asyncio.run(lessons_routes.send_batch(lesson, lessons_routes.Batch(answers=[given(pretest["id"], "Na"), given(open_["id"], "ions move")])))
    with pytest.raises(HTTPException, match="answered once"):
        asyncio.run(lessons_routes.send_batch(lesson, lessons_routes.Batch(answers=[given(pretest["id"], "Na"), given(pretest["id"], "Cl")])))
    elsewhere = db.create_lesson(course, "Elsewhere", "lesson", None)
    asyncio.run(quiz_tools.pose_quiz(elsewhere, "Stray?", "choice", "a", "e", options=["a", "b"]))
    with pytest.raises(HTTPException, match="no such quiz in this lesson"):
        asyncio.run(lessons_routes.send_batch(lesson, lessons_routes.Batch(answers=[given(pretest["id"], "Na"), given(db.blocks(elsewhere)[0]["id"], "a")])))
    monkeypatch.setitem(app._turns, lesson, None)
    with pytest.raises(HTTPException, match="still answering"):
        asyncio.run(lessons_routes.send_batch(lesson, lessons_routes.Batch(answers=[])))
    app._turns.pop(lesson)
    real_grade, graded = app.quiz.grade, []

    def failing_grade(answer_id, correct):
        if graded:
            raise RuntimeError("disk full")
        graded.append(answer_id)
        return real_grade(answer_id, correct)

    monkeypatch.setattr(app.quiz, "grade", failing_grade)
    with pytest.raises(RuntimeError):
        asyncio.run(lessons_routes.send_batch(lesson, lessons_routes.Batch(answers=[given(pretest["id"], "Na"), given(sort["id"], "{}")])))
    monkeypatch.setattr(app.quiz, "grade", real_grade)
    assert all(b["data"]["answer"] is None for b in db.blocks(lesson))  # a refused or failed batch stores nothing
    assert db.row("SELECT COUNT(*) AS n FROM answers WHERE id = ?", graded[0])["n"] == 0 and app._lesson_view(lesson)["batch"] == 1

    asyncio.run(lessons_routes.send_batch(lesson, lessons_routes.Batch(answers=[given(pretest["id"], "Na"), given(open_["id"], "ions move", self_correct=True), given(sort["id"], placed)])))
    pretest, open_, sort, skipped = db.blocks(lesson)
    assert pretest["data"]["correct"] is True and sort["data"]["correct"] is False and sort["data"]["misplaced"] == ["CO2"]
    assert open_["data"]["answer"] == "ions move" and open_["data"]["self_correct"] is True and "correct" not in open_["data"]
    assert skipped["data"]["answer"] is None and app._lesson_view(lesson)["batch"] == 0
    line = turns[-1]
    assert line.startswith(f"[batch results]\nquiz {pretest['id']}: correct\n") and f"quiz {open_['id']}, open, self-graded right" in line
    assert f"quiz {sort['id']}: wrong; misplaced: 'CO2'" in line and line.count("a confident miss") == 1
    assert f"left unanswered: quiz {skipped['id']}" in line and line.endswith("Finish the lesson once its checks are answered.") and "do not pose them again" in line
    assert asyncio.run(quiz_tools.grade_quiz(open_["id"], False, "Name the ions.")) == "graded; a confident miss: re-teach it now"
    with pytest.raises(HTTPException, match="not prepared for offline"):
        asyncio.run(lessons_routes.send_batch(lesson, lessons_routes.Batch(answers=[])))
    # Once sent, the lesson is an ordinary one again: new cards keep their key until graded.
    assert asyncio.run(quiz_tools.pose_quiz(lesson, "After?", "choice", "a", "e", options=["a", "b"])).endswith("end the turn and wait for the answer")
    assert "answer_key" not in db.blocks(lesson)[-1]["data"]
    # Sending nothing leaves offline mode, the way out of a prepare that wrote no checks.
    asyncio.run(lessons_routes.prepare_offline(lesson))
    asyncio.run(lessons_routes.send_batch(lesson, lessons_routes.Batch(answers=[])))
    assert app._lesson_view(lesson)["batch"] == 0 and turns[-1].startswith("[batch results]\nleft unanswered: ")


def test_a_sitting_after_a_gap_opens_with_a_warm_up_of_the_due_cards():
    from wise_scholar import app
    from wise_scholar.routes import courses as courses_routes, learner as learner_routes

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Warm')").lastrowid
    first = db.create_course("Rust", who)["id"]
    second = db.create_course("Welsh", who)["id"]
    cards = [db.add_card(course, None, f"q{i}", "open", [], "a", "e", scheduled=True, due="2026-01-01T00:00:00+00:00")
             for i, course in enumerate([first, second] * 4)]
    assert db.last_activity(who) is None and courses_routes.warmup(first) == {"due": 8}  # never active: a sitting starts
    db.conn.execute("UPDATE cards SET confident_miss = 1 WHERE id = ?", (cards[5],))
    # the plan counts what fits the review page's time box
    assert len(learner_routes.reviews(who)) == 8 and learner_routes.today(who)["due"] == 8 and learner_routes.today(who)["warmup"] == 6
    warm = learner_routes.reviews(who, warmup=True)
    assert len(warm) == 8 and warm[0]["id"] == cards[5]  # a confident miss leads
    assert [c["topic"] for c in warm][1:3] == ["Rust", "Welsh"]  # then mixed across courses
    assert courses_routes.warmup(first) == {"due": 0}  # served once: skipping it does not bring it back within the sitting
    app._warmed[who] -= app.SITTING_GAP

    db.conn.execute("INSERT INTO answers (card_id, answer, confidence, created) VALUES (?, 'x', 0.5, datetime('now', '-30 minutes'))", (cards[0],))
    assert courses_routes.warmup(second) == {"due": 0}  # active half an hour ago: the same sitting
    db.conn.execute("UPDATE answers SET created = datetime('now', '-3 hours') WHERE card_id = ?", (cards[0],))
    assert db.last_activity(who) is not None and courses_routes.warmup(second) == {"due": 8}
    lesson = db.create_lesson(first, "Talk", "lesson", None)
    db.conn.execute("INSERT INTO messages (lesson_id, role, text, created) VALUES (?, 'tutor', 'hi', datetime('now'))", (lesson,))
    assert courses_routes.warmup(first) == {"due": 0}  # a tutor reply answers something the learner just did
    db.conn.execute("UPDATE messages SET created = datetime('now', '-3 hours') WHERE lesson_id = ?", (lesson,))
    assert courses_routes.warmup(first) == {"due": 8}
    # a run of their own code counts too, with its ISO time compared against the other tables' format
    db.conn.execute("INSERT INTO commands (course_id, profile_id, lesson_id, origin, command, consent, started) VALUES (?, ?, ?, 'learner', 'ls', 'none', ?)",
                    (first, who, lesson, app._now()))
    assert courses_routes.warmup(first) == {"due": 0}


def test_a_learner_back_at_an_unfinished_unit_after_three_days_gets_a_recap(monkeypatch):
    import asyncio

    from wise_scholar import app
    from wise_scholar.routes import learner as learner_routes, lessons as lessons_routes

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append((lesson["id"], line)))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Returner')").lastrowid
    course = db.create_course("Haskell", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Folds"], "known": []}])
    lesson = db.create_lesson(course, "Folds", "lesson", db.concepts(course)[0]["id"])
    resume = lambda: asyncio.run(lessons_routes.resume_lesson(lesson))  # noqa: E731
    assert resume() == {"recap": False}  # nothing happened in it yet
    db.conn.execute("INSERT INTO messages (lesson_id, role, text, created) VALUES (?, 'tutor', 'foldr', datetime('now', '-4 days'))", (lesson,))
    opening = db.add_block(lesson, "quiz", "What does foldr build?", {"card_id": 0, "kind": "open", "options": [], "answer": None, "pretest": True})
    assert resume() == {"recap": False}  # the opening is not tried yet: it is where the learner picks up
    db.set_block_data(opening["id"], {**opening["data"], "answer": "a list", "correct": True})
    db.conn.execute("INSERT INTO messages (lesson_id, role, text, created) VALUES (?, 'learner', 'and foldl?', datetime('now', '-4 days'))", (lesson,))
    assert resume() == {"recap": False}  # an unanswered learner message comes first
    db.conn.execute("INSERT INTO messages (lesson_id, role, text, created) VALUES (?, 'tutor', 'left to right', datetime('now', '-2 days'))", (lesson,))
    assert resume() == {"recap": False}
    db.conn.execute("UPDATE messages SET created = datetime('now', '-4 days') WHERE lesson_id = ?", (lesson,))
    monkeypatch.setitem(app._turns, lesson, None)
    assert resume() == {"recap": False}
    app._turns.pop(lesson)
    due = db.add_card(course, None, "q", "open", [], "a", "e", scheduled=True, due="2026-01-01T00:00:00+00:00")
    assert resume() == {"recap": False}  # the warm-up first
    learner_routes.reviews(who, warmup=True)
    assert resume() == {"recap": True} and turns == [(lesson, lessons_routes.RECAP.format(days=4))]
    db.conn.execute("UPDATE cards SET due = NULL WHERE id = ?", (due,))
    assert turns[0][1].startswith("[event] The learner is back after 4 days away from this unit.")
    db.conn.execute("UPDATE lessons SET batch = 1 WHERE id = ?", (lesson,))
    assert resume() == {"recap": False}  # an offline unit carries on from the device
    db.conn.execute("UPDATE lessons SET batch = 0 WHERE id = ?", (lesson,))
    check = db.add_block(lesson, "quiz", "Which fold is lazy?", {"card_id": 0, "kind": "choice", "options": ["foldr", "foldl"], "answer": None})
    assert resume() == {"recap": False}  # an open check is where the learner picks up
    db.set_block_data(check["id"], {**check["data"], "answer": "foldr"})
    db.add_block(lesson, "done", "Finished.", None)
    assert resume() == {"recap": False} and len(turns) == 1


def test_a_unit_outline_counts_its_steps_and_takes_one_added_step_with_a_reason():
    import asyncio
    import json

    from wise_scholar import app
    from wise_scholar.tools import lesson_flow as flow_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Outliner')").lastrowid
    course = db.create_course("OCaml", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Variants"], "known": []}])
    lesson = db.create_lesson(course, "Variants", "lesson", db.concepts(course)[0]["id"])
    run = asyncio.run
    assert run(flow_tools.step_done(lesson)).startswith("error: this lesson has no outline")
    assert run(flow_tools.set_outline(lesson, ["a", "b"])).startswith("error: an outline has 3 to 6")
    assert run(flow_tools.set_outline(lesson, ["Predict", "See", "Practise"], reason="why")).startswith("error: a first outline")
    assert run(flow_tools.set_outline(lesson, ["Predict", " See  the  pattern ", "Practise"])) == "error: cards is required: how many cards the whole unit will show"
    db.add_block(lesson, "prose", "Opening.", None)
    assert run(flow_tools.set_outline(lesson, ["Predict", "See the pattern", "Practise"], cards=1)).startswith("error: cards is the estimate for the whole unit, at least 3")
    assert run(flow_tools.set_outline(lesson, ["Predict", " See  the  pattern ", "Practise"], cards=8)) == "outline shown: step 1 of 3, about 8 cards"
    block = flow_tools._outline(lesson)
    assert block["markdown"] == "1. Predict\n2. See the pattern\n3. Practise" and block["data"]["at"] == 0
    assert run(flow_tools.step_done(lesson)) == "step 1 of 3 done" and flow_tools._outline(lesson)["markdown"].startswith("1. Predict ✓\n2. See")
    assert "outline=step 2 of 3: 'See the pattern' cards=1 of about 8 shown" in app._turn_prompt(db.lesson(lesson), "[event] x")
    assert run(flow_tools.set_outline(lesson, ["Predict", "See the pattern", "Practise", "Check"])) == "error: reason is required when adding a step"
    assert run(flow_tools.set_outline(lesson, ["Predict", "Practise", "Check", "See the pattern"], "r")).startswith("error: keep every earlier step")
    assert run(flow_tools.set_outline(lesson, ["Recap", "Predict", "See the pattern", "Practise"], "r")) == "error: a step goes after the step the learner is on, not before"
    assert run(flow_tools.set_outline(lesson, ["Predict", "See the pattern.", "Practise", "Check"], "r")) == "error: keep every earlier step word for word; missing: 'See the pattern'"
    assert run(flow_tools.set_outline(lesson, ["Predict", "See the pattern", "Practise", "Practise"], "r")) == "error: each step is named differently"
    added = run(flow_tools.set_outline(lesson, ["Predict", "Match on a variant", "See the pattern", "Practise"], " You confused the  two cases. "))
    assert added == "step added: now step 2 of 4"
    data = flow_tools._outline(lesson)["data"]
    assert data["added"] == {"step": "Match on a variant", "reason": "You confused the two cases."} and data["at"] == 1
    assert run(flow_tools.set_outline(lesson, ["Predict", "Match on a variant", "See the pattern", "Practise", "More"], "r")) == "refused: the outline already took its one added step"
    assert run(flow_tools.step_done(lesson, cards=10)) == "step 2 of 4 done" and flow_tools._outline(lesson)["data"]["cards"] == 10
    while flow_tools._outline(lesson)["data"]["at"] < 4:
        run(flow_tools.step_done(lesson))
    assert run(flow_tools.step_done(lesson)) == "refused: every step is already done"
    assert "outline=all 4 steps done" in app._turn_prompt(db.lesson(lesson), "[event] x")
    fourth = db.create_lesson(course, "Full", "lesson", db.concepts(course)[0]["id"])
    run(flow_tools.set_outline(fourth, ["a", "b", "c"], cards=6))
    for _ in range(3):
        run(flow_tools.step_done(fourth))
    assert run(flow_tools.set_outline(fourth, ["a", "b", "c", "d"], "r")) == "refused: every step is already done"
    copy = db.copy_course(course, "OCaml again")["id"]
    copied = [b for b in db.rows("SELECT b.data FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE l.course_id = ? AND b.kind = 'outline'", copy)]
    assert copied and all(json.loads(b["data"])["at"] == 0 for b in copied)  # the copy starts the steps afresh
    other = db.create_lesson(course, "Plan", "interview", None)
    assert run(flow_tools.set_outline(other, ["a", "b", "c"])) == "error: only a unit lesson has an outline"
    third = db.create_lesson(course, "Again", "lesson", db.concepts(course)[0]["id"])
    run(flow_tools.set_outline(third, ["a", "b", "c"], cards=6))
    assert run(flow_tools.finish_lesson(third, "Done.")) == "finished; end the turn" and flow_tools._outline(third)["data"]["at"] == 3


def test_a_course_runs_at_momentum_until_switched_and_speed_lets_the_learner_test_out(monkeypatch):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar import app
    from wise_scholar.tools import course_plan as plan_tools, lesson_flow as flow_tools
    from wise_scholar.routes import courses as courses_routes, lessons as lessons_routes

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Pacer')").lastrowid
    course = db.create_course("Zig", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Comptime"], "known": []}])
    lesson = db.create_lesson(course, "Comptime", "lesson", db.concepts(course)[0]["id"])
    assert db.course(course)["pace"] == "momentum" and " pace=momentum" in app._turn_prompt(db.lesson(lesson), "x")
    with pytest.raises(HTTPException, match="speed mode"):
        asyncio.run(lessons_routes.test_out(lesson, lessons_routes.TestOut(scope="unit")))

    assert asyncio.run(plan_tools.set_pace(course, "speed")) == "pace set to speed"
    assert " pace=speed" in app._turn_prompt(db.lesson(lesson), "x")
    with pytest.raises(HTTPException, match="opening first"):
        asyncio.run(lessons_routes.test_out(lesson, lessons_routes.TestOut(scope="unit")))
    db.add_block(lesson, "quiz", "What runs at compile time?", {"card_id": 0, "kind": "open", "options": [], "answer": "comptime", "pretest": True})
    with pytest.raises(HTTPException, match="no step left"):
        asyncio.run(lessons_routes.test_out(lesson, lessons_routes.TestOut(scope="step")))
    assert asyncio.run(flow_tools.set_outline(lesson, ["Guess", "See comptime", "Use it", "Check", "More"], cards=10)) == "outline shown: step 1 of 5, about 10 cards"
    db.conn.execute("DELETE FROM blocks WHERE lesson_id = ? AND kind = 'outline'", (lesson,))
    asyncio.run(plan_tools.set_pace(course, "momentum"))
    assert asyncio.run(flow_tools.set_outline(lesson, ["Guess", "See comptime", "Use it", "Check", "More"], cards=10)).startswith("error: a first outline here has 3 to 4 steps")
    asyncio.run(plan_tools.set_pace(course, "speed"))
    asyncio.run(flow_tools.set_outline(lesson, ["Guess", "See comptime", "Use it"], cards=6))
    asyncio.run(flow_tools.step_done(lesson))
    asyncio.run(lessons_routes.test_out(lesson, lessons_routes.TestOut(scope="step")))
    assert turns[-1].startswith("[event] The learner tests out of the current outline step (step 2: 'See comptime').")
    asyncio.run(lessons_routes.test_out(lesson, lessons_routes.TestOut(scope="unit")))
    assert turns[-1].startswith("[event] The learner tests out of the whole unit.") and "70% confidence" in turns[-1]
    monkeypatch.setitem(app._turns, lesson, None)
    with pytest.raises(HTTPException, match="still answering"):
        asyncio.run(lessons_routes.test_out(lesson, lessons_routes.TestOut(scope="unit")))
    app._turns.pop(lesson)

    assert courses_routes.set_pace(course, courses_routes.Pace(pace="momentum")) == {"pace": "momentum"} and db.course(course)["pace"] == "momentum"
    with pytest.raises(ValueError):
        courses_routes.Pace(pace="fast")


def test_a_sitting_summary_covers_the_answers_back_to_the_last_two_hour_gap():
    from wise_scholar.routes import learner as learner_routes

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Sitter')").lastrowid
    course = db.create_course("Prolog", who)["id"]
    assert learner_routes.sitting(who) == {"answers": 0}
    card = lambda q: db.add_card(course, None, q, "open", [], "a", "e", scheduled=True)  # noqa: E731
    for question, confidence, correct, ago in [("old", 0.9, 0, "-1 day"), ("unify?", 0.9, 0, "-50 minutes"), ("cut?", 0.8, 1, "-40 minutes"), ("fail?", 0.5, 0, "-10 minutes")]:
        db.conn.execute("INSERT INTO answers (card_id, answer, confidence, correct, created) VALUES (?, 'x', ?, ?, datetime('now', ?))",
                        (card(question), confidence, correct, ago))
    summary = learner_routes.sitting(who)
    assert summary["answers"] == 3 and round(summary["sure"], 3) == round((0.9 + 0.8 + 0.5) / 3, 3) and round(summary["right"], 3) == round(1 / 3, 3)
    assert summary["misses"] == ["unify?"]  # sure and wrong; the unsure miss is not one
    assert summary["current"] is True
    db.conn.execute("UPDATE answers SET created = datetime(created, '-1 day') WHERE card_id IN (SELECT id FROM cards WHERE course_id = ?)", (course,))
    old = learner_routes.sitting(who)
    assert old["answers"] == 3 and old["current"] is False  # the last sitting, over, not this one
    assert len(learner_routes.calibration(who)["buckets"]) > 0  # the calibration panel still reads the same answers
