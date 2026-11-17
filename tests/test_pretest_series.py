import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db, figures  # noqa: E402

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
