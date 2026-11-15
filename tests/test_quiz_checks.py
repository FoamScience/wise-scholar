import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db  # noqa: E402


def test_posed_choice_options_are_shuffled_the_same_way_for_card_and_block():
    import asyncio

    from wise_scholar.tools import quizzes as quiz_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Shuffled')").lastrowid
    lesson = db.create_lesson(db.create_course("Physics", who)["id"], "Placement", "placement")
    written = ["newton", "joule", "watt", "pascal"]
    first = set()
    for n in range(20):
        asyncio.run(quiz_tools.pose_quiz(lesson, f"Unit of force? ({n})", "choice", "newton", "", options=written))
        block = db.blocks(lesson)[-1]
        card = db.card(block["data"]["card_id"])
        assert block["data"]["options"] == card["options"] and sorted(card["options"]) == sorted(written)
        assert card["answer_key"] == "newton"
        first.add(card["options"][0])
    assert len(first) > 1 and written == ["newton", "joule", "watt", "pascal"]
    asyncio.run(quiz_tools.pose_quiz(lesson, "Define force.", "open", "a push or pull", "", options=["stray"]))
    assert db.blocks(lesson)[-1]["data"]["options"] == []


def sort_items():
    from wise_scholar.tools import quizzes as quiz_tools

    item = lambda text, category: quiz_tools.SortItem(text=text, category=category)  # noqa: E731
    return [item("list", "mutable"), item("dict", "mutable"), item("set", "mutable"), item("tuple", "immutable"), item("str", "immutable"), item("frozenset", "immutable")]


def assert_bad_sorts_refused(lesson, items):
    import asyncio

    from wise_scholar.tools import quizzes as quiz_tools

    pose = lambda cats, its: asyncio.run(quiz_tools.pose_sort(lesson, "Which of these can change in place?", cats, its, "A mutable object changes under the same name."))  # noqa: E731
    assert pose(["mutable"], items).startswith("error: a sort needs 2 to 4 distinct categories")
    assert pose(["mutable", "immutable"], items[:5]).startswith("error: a sort needs 6 to 12 distinct items")
    assert pose(["mutable", "immutable"], [*items[:5], quiz_tools.SortItem(text="bytes", category="frozen")]).startswith("error: every item names one of the categories")
    assert pose(["mutable", "immutable", "callable"], items).startswith("error: every item names one of the categories")
    assert pose(["mutable", "immutable"], items).startswith("shown as quiz ")


def assert_sort_is_posed_without_its_key(block, data):
    from wise_scholar import quiz

    assert block["kind"] == "quiz"
    assert data["kind"] == "sort"
    assert data["categories"] == ["mutable", "immutable"]
    assert "answer_key" not in data
    assert sorted(o["text"] for o in data["options"]) == ["dict", "frozenset", "list", "set", "str", "tuple"]
    assert all(set(o) == {"text"} for o in data["options"])  # no category reaches the browser before grading
    card = db.card(data["card_id"])
    assert card["kind"] == "sort"
    assert quiz.public(card)["categories"] == ["mutable", "immutable"]
    assert card["scheduled"] == 1
    assert quiz.public(card)["options"] == data["options"]
    assert card["options"][0]["category"] in ("mutable", "immutable")
    return card


def assert_a_wrong_sort_is_graded_by_placement(turns, who, block, card, data):
    import asyncio
    import json

    from wise_scholar import app, quiz
    from wise_scholar.routes import blocks as blocks_routes, learner as learner_routes

    wrong = json.dumps({o["text"]: ("immutable" if o["text"] in ("tuple", "str", "frozenset", "set") else "mutable") for o in data["options"]})
    asyncio.run(blocks_routes.answer_quiz(block["id"], app.QuizAnswer(answer=wrong, confidence=0.9)))
    graded = db.block(block["id"])["data"]
    assert graded["correct"] is False
    assert graded["misplaced"] == ["set"]
    assert graded["confident_miss"] is True
    assert turns[-1].startswith("[event] Quiz")
    assert "misplaced: 'set'" in turns[-1]
    assert "set → immutable" in turns[-1]
    assert db.errors(who)[-1]["said"] == "set → immutable"
    assert db.errors(who)[-1]["correct"] == "set → mutable"
    reviewed = learner_routes.review_card(card["id"], learner_routes.ReviewAnswer(answer=wrong))
    assert reviewed["correct"] is False
    assert reviewed["misplaced"] == ["set"]
    assert quiz.misplaced(card, "not json") == [o["text"] for o in card["options"]]


def assert_a_sort_reaches_the_vault(course, lesson, block, concept):
    from wise_scholar import obsidian

    note = obsidian.Vault(course)._card_body(db.lesson(lesson), db.block(block["id"]))
    assert "- set → immutable ✗" in note
    assert "**mutable · immutable**" in note
    flash = "\n".join(obsidian.Vault(course)._flashcards(concept))
    assert "- frozenset" in flash
    assert "frozenset → immutable" in flash


def assert_a_teacher_authors_and_edits_a_sort(course, concept, items):
    import asyncio

    from wise_scholar.tools import quizzes as quiz_tools
    from wise_scholar.routes import blocks as blocks_routes

    db.conn.execute("UPDATE courses SET mode = 'teacher' WHERE id = ?", (course,))
    plan = db.create_lesson(course, "Mutability plan", "lesson", concept["id"])
    assert asyncio.run(quiz_tools.pose_sort(plan, "Sort them.", ["mutable", "immutable"], items, "Why.")).startswith("shown")
    authored = db.blocks(plan)[-1]
    assert authored["data"]["options"][0]["category"] in ("mutable", "immutable")
    assert authored["data"]["answer_key"] == '["mutable", "immutable"]'
    edited = blocks_routes.edit_block(authored["id"], blocks_routes.BlockEdit(markdown="Sort these.", options=["x"], answer_key="y", explanation="Because."))
    assert edited["data"]["options"] == authored["data"]["options"]
    assert edited["data"]["answer_key"] == authored["data"]["answer_key"]
    assert edited["data"]["explanation"] == "Because."
    assert db.card(authored["data"]["card_id"])["question"] == "Sort these."


def test_a_sort_check_is_graded_placement_by_placement(monkeypatch):
    import json

    from wise_scholar import app, quiz

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Sorter')").lastrowid
    try:
        course = db.create_course("Python", who)["id"]
        db.set_concepts(course, [{"title": "Types", "concepts": ["Mutability"], "known": []}])
        concept = db.concepts(course)[0]
        lesson = db.create_lesson(course, "Mutability", "lesson", concept["id"])
        items = sort_items()
        assert_bad_sorts_refused(lesson, items)
        block = db.blocks(lesson)[-1]
        data = block["data"]
        card = assert_sort_is_posed_without_its_key(block, data)
        assert_a_wrong_sort_is_graded_by_placement(turns, who, block, card, data)
        assert_a_sort_reaches_the_vault(course, lesson, block, concept)

        right = json.dumps({o["text"]: o["category"] for o in card["options"]})
        assert quiz.auto_correct(card, right) is True
        assert quiz.grade(quiz.submit(card, right, 0.5), True)["misplaced"] == []

        assert_a_teacher_authors_and_edits_a_sort(course, concept, items)
    finally:
        db.delete_course(course)
        db.conn.execute("DELETE FROM profiles WHERE id = ?", (who,))


def test_a_wrong_option_carries_the_belief_behind_it_into_the_feedback_the_notebook_and_the_next_lesson(monkeypatch):
    import asyncio

    from wise_scholar import app, obsidian
    from wise_scholar.tools import quizzes as quiz_tools
    from wise_scholar.routes import blocks as blocks_routes, learner as learner_routes

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Believer')").lastrowid
    course = db.create_course("Physics", who)["id"]
    db.set_concepts(course, [{"title": "Motion", "concepts": ["Falling"], "known": []}])
    falling = db.concepts(course)[0]
    lesson = db.create_lesson(course, "Falling", "lesson", falling["id"])
    options = ["Both land together", "The heavy one first"]
    pose = lambda **k: asyncio.run(quiz_tools.pose_quiz(lesson, "Which lands first in a vacuum?", "choice", "Both land together", "Gravity accelerates both alike.", **k, options=options))  # noqa: E731
    assert pose(misconceptions={"Both land together": "x"}).startswith("error: misconceptions maps wrong options")
    assert pose(misconceptions={"The light one first": "x"}).startswith("error: misconceptions maps wrong options")
    assert pose(misconceptions={"The heavy one first": "heavier objects fall faster"}).startswith("shown as quiz ")
    block = db.blocks(lesson)[-1]
    assert "misconceptions" not in block["data"] and db.card(block["data"]["card_id"])["misconceptions"] == {"The heavy one first": "heavier objects fall faster"}

    asyncio.run(blocks_routes.answer_quiz(block["id"], app.QuizAnswer(answer="The heavy one first", confidence=0.9)))
    graded = db.block(block["id"])["data"]
    assert graded["misconception"] == "heavier objects fall faster" and "from the belief 'heavier objects fall faster'" in turns[-1]
    entry = db.errors(who)[-1]
    assert entry["misconception"] == "heavier objects fall faster"
    assert app._record_line(db.block(block["id"])).endswith("| belief: heavier objects fall faster")
    card_id = block["data"]["card_id"]
    db.add_error(who, course, "quiz", "q", "again", "right", card_id=card_id)
    assert db.errors(who)[-1]["said"] == "again" and db.errors(who)[-1]["misconception"] == "heavier objects fall faster"

    assert "from the belief 'heavier objects fall faster'" in learner_routes._notebook_brief(who, course)
    vault = obsidian.Vault(course).build()
    assert any(b"**Behind this answer**: heavier objects fall faster" in content for content in vault.values())

    asyncio.run(quiz_tools.pose_quiz(lesson, "Why does the feather lag in air?", "open", "Drag", "Air resists."))
    open_block = db.blocks(lesson)[-1]
    asyncio.run(blocks_routes.answer_quiz(open_block["id"], app.QuizAnswer(answer="It is lighter", confidence=0.9)))
    assert asyncio.run(quiz_tools.grade_quiz(open_block["id"], False, "Not the weight.", " lighter things fall slower ")).startswith("graded")
    assert db.block(open_block["id"])["data"]["misconception"] == "lighter things fall slower" and db.errors(who)[0]["misconception"] == "lighter things fall slower"


def test_a_quick_check_asks_one_thing():
    import asyncio

    from wise_scholar.tools import quizzes as quiz_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Single')").lastrowid
    course = db.create_course("Pumps", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Euler head"], "known": []}])
    lesson = db.create_lesson(course, "Euler head", "lesson", db.concepts(course)[0]["id"])
    two = "How does the head line change as $\\beta_2$ grows? Which point does every line share, and why?"
    assert asyncio.run(quiz_tools.pose_quiz(lesson, two, "open", "a", "")).startswith("error: not shown. A quick check asks one thing; this one asks 2")
    one = "How does the head line change as $\\beta_2$ grows from 25° to 90°? Code `x?y` and math $a?b$ do not count."
    assert asyncio.run(quiz_tools.pose_quiz(lesson, one.replace("? Code", ", with code"), "open", "a", "")).startswith("shown as quiz")
    assert asyncio.run(quiz_tools.pose_quiz(lesson, "Which point is shared ؟ لماذا؟", "open", [], "a")).startswith("error: not shown")
