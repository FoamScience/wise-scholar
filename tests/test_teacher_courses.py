import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db, figures, search  # noqa: E402

TEACHES = figures.Teaches(claim="Parts have a place.", notice="Where each part sits.")


def test_a_teacher_profile_prepares_courses_with_the_designer_prompts_and_no_learner_gates(monkeypatch):  # noqa: C901
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar import app
    from wise_scholar.tools import lesson_flow as flow_tools, practice as practice_tools, quizzes as quiz_tools
    from wise_scholar.routes import blocks as blocks_routes, courses as courses_routes, learner as learner_routes

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Ms Teach')").lastrowid
    assert db.profile(who)["mode"] == "learner"
    assert learner_routes.set_mode(who, learner_routes.ProfileMode(mode="teacher"))["mode"] == "teacher"
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
    assert asyncio.run(flow_tools.add_block(lesson, "prose", "Objectives…")) == "shown"
    assert asyncio.run(practice_tools.pose_challenge(lesson, "Predict. " * 120, pretest=True, form="prediction")).startswith("shown")
    opening = db.blocks(lesson)[-1]
    assert asyncio.run(practice_tools.give_hint(opening["id"], "Think of shells.")).startswith("shown as hint 1")
    assert asyncio.run(practice_tools.reveal(opening["id"], "Two bonds.")) == "shown"
    assert asyncio.run(quiz_tools.pose_quiz(lesson, "Valence of carbon?", "choice", "4", "Four electrons.", options=["4", "2"])).startswith("shown")
    assert db.card(db.blocks(lesson)[-1]["data"]["card_id"])["scheduled"] == 0
    assert asyncio.run(flow_tools.finish_lesson(lesson, "Plan done.")) == "finished; end the turn"
    with pytest.raises(HTTPException) as refused:
        asyncio.run(courses_routes.start_placement(course["id"]))
    assert refused.value.status_code == 409 and "prepared course" in refused.value.detail
    # Nobody answers an authored card through the API either.
    for call in (lambda: blocks_routes.answer_quiz(db.blocks(lesson)[-2]["id"], app.QuizAnswer(answer="4", confidence=0.5)),
                 lambda: blocks_routes.attempt(opening["id"], blocks_routes.Answer(answer="x"))):
        with pytest.raises(HTTPException) as closed:
            asyncio.run(call())
        assert closed.value.status_code == 409 and "take no answers" in closed.value.detail

    # A learner's course keeps its gates and its placement flow, retake included.
    learner = db.conn.execute("INSERT INTO profiles (name) VALUES ('Still learning')").lastrowid
    plain = db.create_course("Chemistry", learner)["id"]
    assert db.course(plain)["mode"] == "learner" and app._phase_prompt(db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ?", plain)["id"])) == "interview"
    db.set_concepts(plain, [{"title": "Atoms", "concepts": ["Bonds"], "known": []}])
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: None)
    retake = asyncio.run(courses_routes.retake_placement(plain))
    assert retake["phase"] == "placement"


def test_handouts_give_the_teacher_the_solutions_and_the_students_the_tasks(monkeypatch):
    import asyncio

    from wise_scholar import handout
    from wise_scholar.tools import lesson_flow as flow_tools, practice as practice_tools, quizzes as quiz_tools, visuals as visual_tools
    from wise_scholar.routes import lessons as lessons_routes

    who = db.conn.execute("INSERT INTO profiles (name, mode) VALUES ('Handout', 'teacher')").lastrowid
    course = db.create_course("Chemistry handouts", who)["id"]
    db.set_concepts(course, [{"title": "Atoms", "concepts": ["Bonds"], "known": []}])
    lesson = db.create_lesson(course, "Bonds", "lesson", db.concepts(course)[0]["id"])
    asyncio.run(flow_tools.add_block(lesson, "prose", "## Objectives\n\nCount bonds."))
    asyncio.run(practice_tools.pose_challenge(lesson, "How many bonds does carbon form?", pretest=True, form="prediction"))
    opening = db.blocks(lesson)[-1]
    asyncio.run(practice_tools.give_hint(opening["id"], "Count valence electrons."))
    asyncio.run(practice_tools.reveal(opening["id"], "Four."))
    asyncio.run(quiz_tools.pose_quiz(lesson, "Which is a noble gas?", "choice", "Helium", "Full outer shell.", options=["Helium", "Oxygen"]))
    asyncio.run(visual_tools.add_figure(lesson, '<svg viewBox="0 0 10 10"><circle r="4"/></svg>', "A pair", "two atoms", TEACHES))

    from wise_scholar import sandbox

    monkeypatch.setattr(sandbox, "COMMANDS", True)
    asyncio.run(practice_tools.pose_exercise(lesson, "Count the bonds in water.", [practice_tools.ExerciseFile(path="w/count.py", content="print(2)")], "uv run w/count.py"))
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
    sent = lessons_routes.lesson_handout(lesson, "student")
    assert sent.media_type.startswith("text/markdown") and sent.body.decode() == student
    assert lessons_routes.get_lesson(lesson)["course_id"] == course


def test_a_prepared_course_is_duplicated_with_its_plan_and_without_its_record(tmp_path, monkeypatch):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar import app
    from wise_scholar.tools import practice as practice_tools, quizzes as quiz_tools
    from wise_scholar.routes import courses as courses_routes

    monkeypatch.setattr(app, "SOURCES", tmp_path / "sources")
    monkeypatch.setattr(db, "WORKSPACE", tmp_path / "workspace")
    who = db.conn.execute("INSERT INTO profiles (name, mode) VALUES ('Copier', 'teacher')").lastrowid
    course = db.create_course("Chemistry to copy", who)["id"]
    db.conn.execute("UPDATE courses SET details = 'year 10', hours = 20, mechanism = 'concept-map' WHERE id = ?", (course,))
    db.set_concepts(course, [{"title": "Atoms", "concepts": ["Bonds", "Shells"], "known": []}])
    bonds, shells = db.concepts(course)
    db.add_capstone(course, "Atoms", "Model kit", "Build a model.", "kit", [(shells["id"], "a water model")])
    lesson = db.create_lesson(course, "Bonds", "lesson", bonds["id"])
    asyncio.run(quiz_tools.pose_quiz(lesson, "Valence of carbon?", "choice", "4", "Four.", options=["4", "2"]))
    asyncio.run(practice_tools.pose_challenge(lesson, "Predict the bond.", pretest=True, form="prediction"))
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

    db.add_card(course, None, "Nenne ein Edelgas.", "open", [], "Helium", "", scheduled=False, translation="Name a noble gas.")
    copy = courses_routes.duplicate_course(course)
    assert copy["topic"] == "Chemistry to copy (2)" and copy["mode"] == "teacher" and copy["id"] != course
    assert db.row("SELECT translation FROM cards WHERE course_id = ? AND question = ?", copy["id"], "Nenne ein Edelgas.")["translation"] == "Name a noble gas."
    assert courses_routes.duplicate_course(copy["id"])["topic"] == "Chemistry to copy (3)"
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
    assert len(db.sources(copy["id"])) == 1 and copied_source["status"] == "ready" and search.search(copy["id"], "Atoms", 1, ("source",))[0]["title"].endswith("part 1")
    assert search.search(course, "Atoms", 2, ("source",))[0]["title"].endswith("part 1") and len(db.sources(course)) == 2
    assert (tmp_path / "sources" / str(copy["id"]) / f"{copied_source['id']}-syllabus.md").read_text() == "Atoms first."
    assert (db.workspace(new["slug"]) / "demo.py").read_text() == "print(1)"
    assert db.commands(who) == [] and db.graded_answers(who) == []
    learner = db.conn.execute("INSERT INTO profiles (name) VALUES ('No copy')").lastrowid
    with pytest.raises(HTTPException) as refused:
        courses_routes.duplicate_course(db.create_course("Mine", learner)["id"])
    assert refused.value.status_code == 409


def test_a_teacher_edits_removes_and_reorders_the_cards_of_a_plan():
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar.tools import lesson_flow as flow_tools, practice as practice_tools, quizzes as quiz_tools
    from wise_scholar.routes import blocks as blocks_routes

    who = db.conn.execute("INSERT INTO profiles (name, mode) VALUES ('Editor', 'teacher')").lastrowid
    course = db.create_course("Chemistry edits", who)["id"]
    db.set_concepts(course, [{"title": "Atoms", "concepts": ["Bonds"], "known": []}])
    lesson = db.create_lesson(course, "Bonds", "lesson", db.concepts(course)[0]["id"])
    asyncio.run(flow_tools.add_block(lesson, "prose", "## Objectives\n\nCount bonds."))
    asyncio.run(practice_tools.pose_challenge(lesson, "How many bonds?", pretest=True, form="prediction"))
    asyncio.run(quiz_tools.pose_quiz(lesson, "Noble gas?", "choice", "Helium", "Full shell.", options=["Helium", "Oxygen"]))
    prose, task, quiz = db.blocks(lesson)

    edited = blocks_routes.edit_block(task["id"], blocks_routes.BlockEdit(markdown="How many bonds does carbon form?", solution="Four.", hints=["Count electrons.", " ", "Think shells."]))
    assert edited["markdown"] == "How many bonds does carbon form?" and edited["data"]["solution"] == "Four." and edited["data"]["hints"] == ["Count electrons.", "Think shells."]
    with pytest.raises(HTTPException) as bad:
        blocks_routes.edit_block(quiz["id"], blocks_routes.BlockEdit(options=["Helium", "Neon"], answer_key="Argon"))
    assert bad.value.status_code == 422
    edited = blocks_routes.edit_block(quiz["id"], blocks_routes.BlockEdit(markdown="Which is a noble gas?", options=["Helium", "Neon", "Oxygen"], answer_key="Neon", explanation="Also full."))
    card = db.card(quiz["data"]["card_id"])
    assert (card["question"], card["options"], card["answer_key"], card["explanation"]) == ("Which is a noble gas?", ["Helium", "Neon", "Oxygen"], "Neon", "Also full.")
    assert edited["data"]["answer_key"] == "Neon" and edited["data"]["options"] == ["Helium", "Neon", "Oxygen"]

    order = blocks_routes.move_block(quiz["id"], blocks_routes.Move(direction="up"))
    assert [b["id"] for b in order] == [prose["id"], quiz["id"], task["id"]]
    order = blocks_routes.move_block(prose["id"], blocks_routes.Move(direction="up"))
    assert [b["id"] for b in order] == [prose["id"], quiz["id"], task["id"]]  # already first
    blocks_routes.remove_block(quiz["id"])
    assert [b["id"] for b in db.blocks(lesson)] == [prose["id"], task["id"]] and db.card(card["id"]) is None

    learner = db.conn.execute("INSERT INTO profiles (name) VALUES ('Reader only')").lastrowid
    plain = db.create_course("Chemistry plain", learner)["id"]
    plain_lesson = db.row("SELECT id FROM lessons WHERE course_id = ?", plain)["id"]
    block = db.add_block(plain_lesson, "prose", "Hello", {})
    with pytest.raises(HTTPException) as refused:
        blocks_routes.edit_block(block["id"], blocks_routes.BlockEdit(markdown="Changed"))
    assert refused.value.status_code == 409
