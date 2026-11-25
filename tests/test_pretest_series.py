import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db, figures, obsidian  # noqa: E402

TEACHES = figures.Teaches(claim="Parts have a place.", notice="Where each part sits.")


def test_pretest_gates_explanations_and_stays_out_of_reviews_and_mastery():
    import asyncio

    from wise_scholar.tools import lesson_flow as flow_tools, quizzes as quiz_tools, visuals as visual_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Pre')").lastrowid
    course = db.create_course("Rust", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Ownership", "Traits"], "known": ["Traits"]}])
    own, traits = db.concepts(course)
    lesson = db.create_lesson(course, "Ownership", "lesson", own["id"])
    assert asyncio.run(flow_tools.add_block(lesson, "prose", "Ownership means…")).startswith("refused: the lesson has no attempted opening")
    svg = '<svg viewBox="0 0 10 10"><circle r="4"/></svg>'
    assert asyncio.run(visual_tools.add_figure(lesson, svg, "c", "a", TEACHES)).startswith("refused: the lesson has no attempted opening")
    assert not asyncio.run(visual_tools.add_figure(lesson, svg, "c", "a", TEACHES, setup=True)).startswith(("refused", "error"))
    assert asyncio.run(visual_tools.add_plot(lesson, "t", {"marks": [{"type": "rule", "y": 0}]}, "a", TEACHES)).startswith("refused: the lesson has no attempted opening")
    assert asyncio.run(visual_tools.add_plot(lesson, "t", {"marks": [{"type": "rule", "y": 0}]}, "a", TEACHES, setup=True)).startswith("refused: an opening has one setup figure")
    assert asyncio.run(flow_tools.add_block(lesson, "prose", "Ownership means…")).startswith("refused: the lesson has no attempted opening")
    asyncio.run(quiz_tools.pose_quiz(lesson, "What happens to s after let t = s;?", "open", "s is moved", "", pretest=True))
    block = db.blocks(lesson)[-1]
    card = db.card(block["data"]["card_id"])
    assert card["concept_id"] is None and card["scheduled"] == 0 and block["data"]["pretest"]
    assert asyncio.run(flow_tools.add_block(lesson, "prose", "Ownership means…")).startswith("refused")
    db.set_block_data(block["id"], {**block["data"], "answer": "it is copied", "answer_id": 1})
    assert asyncio.run(flow_tools.add_block(lesson, "prose", "Ownership means…")) == "shown"
    assert db.concept_mastery(course) == {}

    known_lesson = db.create_lesson(course, "Traits", "lesson", traits["id"])
    assert asyncio.run(flow_tools.add_block(known_lesson, "prose", "Traits are…")) == "shown"


def test_series_episodes_keep_memory_and_pass_a_stricter_gate():
    import asyncio

    from wise_scholar.tools import language as language_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Story')").lastrowid
    course = db.create_course("German", who)["id"]
    db.course_lang(course, "de")
    db.set_vocab_tier(who, "de", 30)
    lesson = db.create_lesson(course, "Episode 1", "story")
    gloss = language_tools.Gloss
    assert "no series yet" in asyncio.run(language_tools.add_episode(lesson, "t", "x " * 500, "de-DE", "r"))
    assert asyncio.run(language_tools.start_series(course, "Lena in Köln", ["Lena: Studentin", "Omar: Nachbar"], "Lena zieht nach Köln.")).startswith("started")
    assert "already has a series" in asyncio.run(language_tools.start_series(course, "x", [], ""))
    sentence = "Lena geht am Morgen in die Stadt und kauft Brot, dann trifft sie Omar vor dem Haus und sie reden über das Wetter. "
    text = sentence * 20
    assert "words" in asyncio.run(language_tools.add_episode(lesson, "Brot", sentence * 5, "de-DE", "r"))
    assert "at most 5 glossary" in asyncio.run(language_tools.add_episode(lesson, "Brot", text, "de-DE", "r", glossary=[gloss(word="Brot", meaning="bread")] * 6))
    rare = text + "Die Thrombozytenzahl der Bürgschaftserklärung war unleserlich. " * 8
    assert asyncio.run(language_tools.add_episode(lesson, "Brot", rare, "de-DE", "r")).startswith("rewrite")
    assert asyncio.run(language_tools.add_episode(lesson, "Brot", text, "de-DE", "Lena kauft Brot und trifft Omar.")).startswith("shown as episode 1")
    show = db.series(course)
    assert show["episodes"] == 1 and "Lena kauft Brot" in show["synopsis"]
    block = db.blocks(lesson)[-1]
    assert block["kind"] == "reading" and block["data"]["story"] == "Lena in Köln" and block["data"]["episode"] == 1


def test_a_roleplay_ends_with_its_mistakes_as_review_cards_and_counts_as_output():
    import asyncio

    from wise_scholar.tools import language as language_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Role')").lastrowid
    course = db.create_course("German", who)["id"]
    db.course_lang(course, "de")
    story = db.create_lesson(course, "Episode 1", "story")
    assert asyncio.run(language_tools.end_roleplay(story, [], "x")).startswith("error: only a role-play")
    lesson = db.create_lesson(course, "Role-play 1", "roleplay")
    db.add_message(lesson, "learner", "Ich möchte ein Kaffee.")
    mistake = language_tools.Mistake(said="Ich  möchte\nein Kaffee.", correct="Ich möchte einen Kaffee.", explanation="Kaffee is masculine: einen in the accusative.")
    Mistake = language_tools.Mistake
    end = lambda *ms: asyncio.run(language_tools.end_roleplay(lesson, list(ms), "Good."))  # noqa: E731
    assert end(*[mistake] * 9).startswith("error: at most 8 mistakes")
    assert end(mistake, Mistake(said=" ", correct="x", explanation="")) == "error: mistake 2 has a blank said or correct"
    assert end(Mistake(said="ein Kaffee", correct="ein  Kaffee", explanation="")) == "error: mistake 1: correct is the same as said"
    assert end(Mistake(said="Ich habe Hunger.", correct="Ich bin hungrig.", explanation="")).startswith("error: mistake 1: 'Ich habe Hunger.' is not in the learner's messages")
    assert db.errors(who, course) == []
    assert asyncio.run(language_tools.end_roleplay(lesson, [mistake], "Good.")).startswith("ended with 1 review cards")
    assert asyncio.run(language_tools.end_roleplay(lesson, [mistake], "Good.")).startswith("error: this role-play is already ended")
    [error] = db.errors(who, course)
    card = db.card(error["card_id"])
    assert error["said"] == mistake.said and error["prompt"] == "Role-play 1"
    assert card["answer_key"] == mistake.correct and card["scheduled"] == 1 and mistake.said in card["question"]
    done = db.blocks(lesson)[-1]
    assert done["kind"] == "done"
    assert "Role-play finished" in obsidian.Vault(course)._done_text(done)
    assert "Unit covered" in obsidian.Vault(course)._done_text({**done, "data": {}})
    assert db.strand_counts(course)["output"] == 1


def test_a_roleplay_turn_says_nothing_after_its_end_and_the_next_turn_is_kept(monkeypatch):
    import asyncio

    from wise_scholar import app
    from wise_scholar.tools import language as language_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Closer')").lastrowid
    course = db.create_course("German", who)["id"]
    lesson = db.create_lesson(course, "Role-play 1", "roleplay")
    usage = {"model": "m", "input": 1, "output": 2, "cache_read": 0, "cache_write": 0, "cost": 0.01}
    published = []

    async def closing(prompt, **kwargs):
        yield {"type": "chat.delta", "text": "Tschüss!"}
        yield {"type": "chat.break"}
        assert (await language_tools.end_roleplay(lesson, [], "Good.")).startswith("ended with 0")
        yield {"type": "chat.break"}
        yield {"type": "chat.delta", "text": "Here is a recap."}
        yield {"type": "chat.delta", "text": " More recap."}
        yield {"type": "turn.done", "ok": True, "error": None, "usage": usage}

    async def answering(prompt, **kwargs):
        yield {"type": "chat.delta", "text": "Gern geschehen."}
        yield {"type": "turn.done", "ok": True, "error": None, "usage": usage}

    def run(backend_turn):
        published.clear()
        monkeypatch.setattr(app.backend, "run_turn", backend_turn)
        app._turns[lesson] = None
        asyncio.run(app._run_turn(db.lesson(lesson), "[learner] go"))
        return [e["text"] for e in published if e["type"] == "chat.delta"]

    monkeypatch.setattr(app.hub, "publish", lambda course_id, event: published.append(event))
    assert run(closing) == ["Tschüss!", "\n\n"]
    said = "SELECT text FROM messages WHERE lesson_id = ? AND role = 'tutor' ORDER BY id"
    assert [m["text"] for m in db.rows(said, lesson)] == ["Tschüss!"]
    assert [e["message"]["text"] for e in published if e["type"] == "turn.done"] == ["Tschüss!"]
    assert db.row("SELECT COUNT(*) AS n, SUM(output) AS output FROM usage WHERE lesson_id = ?", lesson) == {"n": 1, "output": 2}

    assert run(answering) == ["Gern geschehen."]
    assert [m["text"] for m in db.rows(said, lesson)] == ["Tschüss!", "Gern geschehen."]


def test_capstone_milestones_follow_the_module_and_complete_on_mark_solved():
    import asyncio

    from wise_scholar import challenge, tutor
    from wise_scholar.tools import course_plan as plan_tools, practice as practice_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Cap')").lastrowid
    course = db.create_course("Rust", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Ownership", "Traits"], "known": []}, {"title": "Async", "concepts": ["Futures"], "known": []}])
    own, traits = [c for c in db.concepts(course) if c["kind"] == "concept"][:2]
    ms = plan_tools.Milestone
    assert "no module" in asyncio.run(plan_tools.set_capstone(course, "Nope", "t", "b", []))
    assert "every concept" in asyncio.run(plan_tools.set_capstone(course, "Basics", "t", "b", [ms(concept="Traits", deliverable="x")]))
    res = asyncio.run(plan_tools.set_capstone(course, "Basics", "A CLI todo", "Build a todo tool.", [ms(concept="Ownership", deliverable="store items"), ms(concept="Traits", deliverable="print them")]))
    assert res.startswith("set; project folder projects/basics/")
    assert (db.workspace(db.course(course)["slug"]) / "projects/basics").is_dir()
    assert "already has" in asyncio.run(plan_tools.set_capstone(course, "Basics", "t", "b", []))

    lesson = db.create_lesson(course, "Ownership", "lesson", own["id"])
    brief = tutor.capstone_brief(db.lesson(lesson))
    assert "milestone 1 of 2" in brief and "store items" in brief and "projects/basics/" in brief
    last = tutor.capstone_brief(db.lesson(db.create_lesson(course, "Traits", "lesson", traits["id"])))
    assert "integration milestone" in last and "far-transfer" in last

    block = db.add_block(lesson, "challenge", "Store items", {**challenge.new(), "milestone": True, "attempts": ["done"]})
    assert asyncio.run(practice_tools.mark_solved(block["id"])) == "marked; milestone done"
    cap = db.capstones(course)[0]
    assert cap["done"] == 1 and [m["done"] for m in cap["milestones"]] == [1, 0]
    transfer = db.add_block(lesson, "challenge", "Transfer", {**challenge.new(), "transfer": True, "max_hints": 0})
    assert "no hint ladder" in challenge.hint_blocker(transfer["data"])


def test_a_long_pretest_is_refused_and_a_short_one_shown(hints):
    import asyncio

    from wise_scholar import tutor
    from wise_scholar.tools import practice as practice_tools, quizzes as quiz_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Brief')").lastrowid
    course = db.create_course("CAD", who)["id"]
    db.set_concepts(course, [{"title": "Shapes", "concepts": ["Topology"], "known": []}])
    lesson = db.create_lesson(course, "Topology", "lesson", db.concepts(course)[0]["id"])
    lecture = "Predict before anything runs. " * 40
    assert asyncio.run(practice_tools.pose_challenge(lesson, lecture, pretest=True)).startswith("error: not shown. A pretest is one question")
    assert asyncio.run(quiz_tools.pose_quiz(lesson, lecture, "open", "x", "", pretest=True)).startswith("error: not shown")
    assert asyncio.run(quiz_tools.pose_quiz(lesson, "x" * 600, "choice", "b", "", pretest=True, options=["a" * 100, "b"])).startswith("error: not shown")
    assert db.blocks(lesson) == [] and db.row("SELECT COUNT(*) AS n FROM cards WHERE course_id = ?", course)["n"] == 0
    assert asyncio.run(practice_tools.pose_challenge(lesson, lecture, milestone=True)).startswith("shown")
    assert asyncio.run(practice_tools.pose_challenge(lesson, "x" * tutor.PRETEST_CHARS, pretest=True)).startswith("shown")
    assert asyncio.run(practice_tools.pose_challenge(lesson, "x" * (tutor.PRETEST_CHARS + 1), pretest=True)).startswith("error: not shown")

    from wise_scholar import history, obsidian

    sides = ("```py\nn*(n+1)//2\n```", "```py\nsum(range(n+1))\n```")
    ask = "When is each the better choice?"
    assert asyncio.run(practice_tools.pose_comparison(lesson, "Sum 1..n", *sides, ask)) == "error: a comparison follows a challenge the learner solved in this lesson"
    last = db.blocks(lesson)[-1]
    db.set_block_data(last["id"], {**last["data"], "solved": True})
    assert asyncio.run(practice_tools.pose_comparison(lesson, "Sum 1..n", "", "loop", ask)) == "error: the problem, both solutions and the question are required"
    assert asyncio.run(practice_tools.pose_comparison(lesson, "Sum 1..n", *sides, " ")).startswith("error: the problem")
    assert asyncio.run(practice_tools.pose_comparison(lesson, "Sum 1..n", "x" * 3001, "loop", ask)).startswith("error: each solution")
    assert asyncio.run(practice_tools.pose_comparison(lesson, " Sum 1..n ", sides[0], " " + sides[1] + " ", ask)).startswith("shown as challenge")
    compared = db.blocks(lesson)[-1]
    assert compared["kind"] == "challenge" and compared["data"]["comparison"] == {"left": sides[0], "right": sides[1], "question": ask}
    assert compared["markdown"] == "Sum 1..n" and "form" not in compared["data"] and compared["data"]["max_hints"] == 3
    assert asyncio.run(practice_tools.pose_comparison(lesson, "p", "a", "b", ask)) == "error: this lesson already has its comparison"
    assert asyncio.run(practice_tools.give_hint(compared["id"], "Count the operations.")) == "shown as hint 1 of 3"
    db.set_block_data(compared["id"], {**db.block(compared["id"])["data"], "attempts": ["a", "b", "c"]})
    assert asyncio.run(practice_tools.reveal(compared["id"], "One is O(1), one is O(n).")) == "shown"
    assert history._line(db.block(compared["id"])).startswith("comparison: Sum 1..n")
    note = obsidian.Vault(course)._card_body(db.lesson(lesson), db.block(compared["id"]))
    assert "**Solution 2**" in note and sides[1] in note and ask in note
    db.course_lang(course, "de")
    assert asyncio.run(practice_tools.pose_comparison(lesson, "p", "a", "b", ask)) == "error: a comparison is for technical subjects, not a language course"
    db.conn.execute("UPDATE courses SET lang = NULL WHERE id = ?", (course,))


def test_a_comparison_is_posed_in_a_lesson_that_holds_prose_an_example_and_its_closing_card():
    import asyncio

    from wise_scholar.tools import lesson_flow as flow_tools, practice as practice_tools

    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Weighing')").lastrowid
    course = db.create_course("Sums", who)["id"]
    db.set_concepts(course, [{"title": "Basics", "concepts": ["Series"], "known": ["Series"]}])
    lesson = db.create_lesson(course, "Series", "lesson", db.concepts(course)[0]["id"])
    compare = ("Sum 1..n", "n*(n+1)//2", "sum(range(n+1))", "When is each the better choice?")
    assert asyncio.run(flow_tools.add_block(lesson, "prose", "A sum adds terms.")) == "shown"
    assert asyncio.run(flow_tools.add_block(lesson, "example", "1 + 2 + 3 = 6")) == "shown"
    assert asyncio.run(practice_tools.pose_comparison(lesson, *compare)) == "error: a comparison follows a challenge the learner solved in this lesson"
    assert asyncio.run(practice_tools.pose_challenge(lesson, "Sum 1..10")).startswith("shown")
    task = db.blocks(lesson)[-1]
    db.set_block_data(task["id"], {**task["data"], "attempts": ["55"]})
    assert asyncio.run(practice_tools.mark_solved(task["id"])).startswith("marked")
    assert asyncio.run(practice_tools.pose_comparison(lesson, *compare)).startswith("shown as challenge")
    assert asyncio.run(practice_tools.pose_comparison(lesson, *compare)) == "error: this lesson already has its comparison"

    again = db.create_lesson(course, "Series", "lesson", db.concepts(course)[0]["id"])
    assert asyncio.run(flow_tools.finish_lesson(again, "You can sum.")) == "finished; end the turn"
    assert db.blocks(again)[-1]["kind"] == "done" and db.blocks(again)[-1]["data"] is None
    assert asyncio.run(practice_tools.pose_comparison(again, *compare)) == "error: a comparison follows a challenge the learner solved in this lesson"


def test_a_pretest_challenge_takes_one_try_and_then_shows_its_answer(monkeypatch):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from wise_scholar import app
    from wise_scholar.routes import blocks as blocks_routes
    from wise_scholar.tools import practice as practice_tools

    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Once')").lastrowid
    course = db.create_course("Optics", who)["id"]
    db.set_concepts(course, [{"title": "Light", "concepts": ["Refraction"], "known": []}])
    lesson = db.create_lesson(course, "Refraction", "lesson", db.concepts(course)[0]["id"])
    asyncio.run(practice_tools.pose_challenge(lesson, "Predict: does a straw in water look bent up or down?", pretest=True))
    opening = db.blocks(lesson)[-1]
    assert opening["data"]["reveal_after"] == 1 and opening["data"]["max_hints"] == 0
    assert asyncio.run(practice_tools.reveal(opening["id"], "Up.")).startswith("refused: the solution is locked")

    asyncio.run(blocks_routes.attempt(opening["id"], blocks_routes.Answer(answer="down")))
    assert turns[-1].startswith(f"[learner attempt] opening (one try) challenge {opening['id']}; attempts 1;")
    with pytest.raises(HTTPException) as again:
        asyncio.run(blocks_routes.attempt(opening["id"], blocks_routes.Answer(answer="up")))
    assert again.value.status_code == 409
    assert asyncio.run(practice_tools.reveal(opening["id"], "Up: light bends away from the normal leaving water.")) == "shown"


def test_a_confident_miss_on_the_opening_quiz_asks_for_no_reteach():
    from wise_scholar import app

    lesson = {"phase": "lesson"}
    card = {"kind": "choice", "answer_key": "4"}
    miss = {"confident_miss": True}
    assert "re-teach" not in app._answer_verdict(card, False, miss, lesson, pretest=True)
    assert app._answer_verdict(card, False, miss, lesson, pretest=False).endswith("a confident miss: re-teach it now")
