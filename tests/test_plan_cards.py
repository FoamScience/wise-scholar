import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db  # noqa: E402


def test_a_question_card_may_take_several_answers():
    import asyncio

    from wise_scholar import app
    from wise_scholar.tools import lesson_flow as flow_tools
    from wise_scholar.routes import blocks as blocks_routes

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Many')").lastrowid
    course = db.create_course("Statistics", who)["id"]
    interview = db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"]
    assert asyncio.run(flow_tools.ask(interview, "What do you already use?", ["Excel"])).startswith("error: a question card takes")
    assert asyncio.run(flow_tools.ask(interview, "What do you already use?", ["Excel", "Python", "R"], multiple=True)).startswith("shown")
    block = db.blocks(interview)[-1]
    assert block["data"]["multiple"] is True and block["data"]["answer"] is None
    turns = []
    app_turn = app._start_turn
    app._start_turn = lambda lesson, line: turns.append(line)
    try:
        asyncio.run(blocks_routes.answer_question(block["id"], blocks_routes.Answer(answer="Excel; R")))
    finally:
        app._start_turn = app_turn
    assert db.block(block["id"])["data"]["answer"] == "Excel; R" and "Excel; R" in turns[0]


def test_a_goal_card_records_what_the_learner_rules_out_as_non_goals(monkeypatch):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar import app
    from wise_scholar.tools import lesson_flow as flow_tools
    from wise_scholar.routes import blocks as blocks_routes

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Ruler')").lastrowid
    course = db.create_course("Welding", who)["id"]
    interview = db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"]
    asyncio.run(flow_tools.ask(interview, "What should you be able to do?", ["MIG", "TIG", "Stick"], non_goals=True))
    goal = db.blocks(interview)[-1]
    assert goal["data"]["multiple"] is True and goal["data"]["non_goals"] == []
    asyncio.run(flow_tools.ask(interview, "Which tools?", ["Grinder", "Clamp"], multiple=True))
    plain = db.blocks(interview)[-1]

    with pytest.raises(HTTPException) as refused:
        asyncio.run(blocks_routes.answer_question(plain["id"], blocks_routes.Answer(answer="Clamp", non_goals=["Grinder"])))
    assert refused.value.status_code == 422
    with pytest.raises(HTTPException):
        asyncio.run(blocks_routes.answer_question(goal["id"], blocks_routes.Answer(answer="MIG", non_goals=["Gas"])))

    asyncio.run(blocks_routes.answer_question(goal["id"], blocks_routes.Answer(answer="", non_goals=["Stick", "TIG", "Stick"])))
    data = db.block(goal["id"])["data"]
    assert data["answer"] == "" and data["non_goals"] == ["Stick", "TIG"]
    assert "not wanted: 'Stick; TIG'" in turns[0]
    assert db.facts(course)[-1]["text"].endswith("leave out: Stick; TIG")
    assert "leave out: Stick; TIG" in app._turn_prompt(db.lesson(interview), "[event] x")


def test_reviews_are_short_cards_and_a_missed_one_is_broken_into_parts(monkeypatch):
    import asyncio

    from wise_scholar import app, quiz
    from wise_scholar.tools import side_turns as side_tools
    from wise_scholar.routes import learner as learner_routes

    queued = []
    monkeypatch.setattr(app, "_queue_cards", queued.append)
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Glancer')").lastrowid
    course = db.create_course("Fans", who)["id"]
    db.set_concepts(course, [{"title": "Blades", "concepts": ["Camber"], "known": []}])
    concept = db.concepts(course)[0]["id"]
    due = "2026-01-01T00:00:00+00:00"
    long = db.add_card(course, concept, "Sort each line by what it does to the shape stored in the document. " * 3, "open", [], "a", "e", scheduled=True, due=due)
    short = db.add_card(course, concept, "Which surface does a blade's camber line live on?", "choice", ["Mean", "Pressure"], "Mean", "Midway.", scheduled=True, due=due)
    assert quiz.is_long(db.card(long)) and not quiz.is_long(db.card(short))
    assert quiz.is_long({"kind": "choice", "question": "Q?", "options": ["a", "b", "c", "d"], "answer_key": "a"})

    assert [c["id"] for c in learner_routes.reviews(who)] == [short] and queued == [("short", course)]
    assert learner_routes.today(who)["due"] == 1

    missed = learner_routes.review_card(short, learner_routes.ReviewAnswer(answer="Pressure"))
    assert missed["correct"] is False and missed["confident_miss"] is False and queued[-1] == ("miss", short)
    assert db.row("SELECT stated FROM answers WHERE id = ?", missed["answer_id"])["stated"] == 0
    assert learner_routes.calibration(who)["n"] == 0  # a review states no confidence
    shown = learner_routes.review_card(long, learner_routes.ReviewAnswer())
    assert shown["answer_key"] == "a"
    learner_routes.self_grade(shown["answer_id"], app.SelfGrade(correct=True))
    assert queued[-1] == ("miss", short)

    prompt = app._cards_prompt(db.lesson(db.row("SELECT id FROM lessons WHERE course_id = ?", course)["id"]), [db.card(short)], "Pressure")
    assert "job=miss" in prompt and f"[card {short}, choice]" in prompt and "options: " in prompt and "Pressure" in prompt.splitlines()[-1]

    side_tools.card_jobs[short] = "miss"
    split = lambda parts: asyncio.run(side_tools.split_card(course, short, [side_tools.ShortCard(**p) for p in parts]))  # noqa: E731
    assert split([{"question": "Q?", "kind": "choice", "options": ["a", "b", "c", "d"], "answer_key": "a"}]).startswith("error: part 1: a choice part has 2 to 3")
    assert split([{"question": "Q" * 141, "kind": "open", "answer_key": "a"}]) == "error: part 1 is too long or empty; keep to the limits above"
    assert split([{"question": "Q?", "kind": "open", "answer_key": "a"}] * 5) == "error: give 1 to 4 parts"
    made = split([
        {"question": "What is a camber line?", "kind": "open", "answer_key": "The line midway between both faces"},
        {"question": "Midway between which faces?", "kind": "choice", "options": ["Pressure and suction", "Hub and tip"], "answer_key": "Pressure and suction"},
    ])
    assert made.startswith(f"card {short} replaced by cards") and short not in side_tools.card_jobs
    parts = db.rows("SELECT * FROM cards WHERE parent_id = ?", short)
    assert [p["origin"] for p in parts] == ["miss", "miss"] and all(p["fsrs"] is None and p["concept_id"] == concept for p in parts)
    assert db.card(short)["retired"] == 1 and short not in [c["id"] for c in db.due_cards(who, app._now())]
    assert {c["id"] for c in learner_routes.reviews(who)} == {p["id"] for p in parts}
    # the retired card's miss no longer holds the concept's mastery down
    assert db.concept_mastery(course) == {concept: 1.0}

    part = parts[0]["id"]
    learner_routes.self_grade(learner_routes.review_card(part, learner_routes.ReviewAnswer())["answer_id"], app.SelfGrade(correct=False))
    assert queued[-1] != ("miss", part)  # a part made from a miss is not broken up again

    side_tools.card_jobs[long] = "short"
    asyncio.run(side_tools.split_card(course, long, [side_tools.ShortCard(question="Short?", kind="open", answer_key="a")]))
    kept = db.row("SELECT * FROM cards WHERE parent_id = ?", long)
    assert kept["origin"] == "short" and kept["due"] == db.card(long)["due"] and kept["fsrs"] == db.card(long)["fsrs"]
    # a card made short keeps its answer in the mastery until its part is answered
    assert db.concept_mastery(course) == {concept: 0.5}
    learner_routes.self_grade(learner_routes.review_card(kept["id"], learner_routes.ReviewAnswer())["answer_id"], app.SelfGrade(correct=False))
    assert db.concept_mastery(course) == {concept: 0.0}


def test_a_cards_job_goes_on_while_turns_make_cards_short(monkeypatch):
    import asyncio

    from wise_scholar import app
    from wise_scholar.tools import side_turns as side_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Shortener')").lastrowid
    course = db.create_course("Pumps", who)["id"]
    longs = [db.add_card(course, None, "Long " * 40, "open", [], "a", "e", scheduled=True, due="2026-01-01T00:00:00+00:00") for _ in range(app.CARDS_PER_TURN + 1)]
    seen = []

    async def turn(lesson, prompt, kind, what):
        seen.append(prompt)
        for card_id in list(side_tools.card_jobs):
            await side_tools.split_card(course, card_id, [side_tools.ShortCard(question="Short?", kind="open", answer_key="a")])
        return True

    monkeypatch.setattr(app, "_background_turn", turn)
    assert asyncio.run(app._shorten(("short", course))) == "more" and len(seen[0].splitlines()) == 2 + app.CARDS_PER_TURN
    assert asyncio.run(app._shorten(("short", course))) == "more"
    assert asyncio.run(app._shorten(("short", course))) == "done" and len(seen) == 2
    assert all(db.card(c)["retired"] for c in longs) and side_tools.card_jobs == {}


def test_a_card_made_short_before_its_answer_hands_its_schedule_to_its_parts():
    import asyncio

    from wise_scholar import app, quiz
    from wise_scholar.tools import side_turns as side_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Early')").lastrowid
    course = db.create_course("Impellers", who)["id"]
    long = db.add_card(course, None, "Long " * 40, "open", [], "a", "e", scheduled=True)
    assert app._job_cards("short", course)[1] == []  # not answered yet: nothing for its parts to keep

    side_tools.card_jobs[long] = "short"
    asyncio.run(side_tools.split_card(course, long, [side_tools.ShortCard(question=f"Part {n}?", kind="open", answer_key="a") for n in (1, 2)]))
    first, second = (p["id"] for p in db.rows("SELECT id FROM cards WHERE parent_id = ? ORDER BY id", long))
    assert db.card(first)["due"] is None
    quiz.grade(quiz.submit(db.card(first), "a", 0.9), True)
    before = db.card(first)["due"]

    quiz.grade(quiz.submit(db.card(long), "b", 0.9), False)
    parent = db.card(long)
    assert db.card(second)["due"] == parent["due"] and db.card(second)["fsrs"] == parent["fsrs"]
    assert db.card(first)["due"] == before  # a part already answered keeps its own schedule
    db.delete_course(course)
    db.conn.execute("DELETE FROM profiles WHERE id = ?", (who,))
