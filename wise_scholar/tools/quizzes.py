import json
import re
from typing import Literal

import simplemma
from pydantic import BaseModel

from .. import db, quiz
from ..tutor import _pretest_length_error, _show, _shuffled, keyed, mcp, prepared


class SortItem(BaseModel):
    text: str
    category: str


# The placement card adds "I don't know" as one more option.
PLACEMENT_OPTIONS = 4


CODE_OR_MATH = re.compile(r"```.*?```|`[^`]*`|\$\$.*?\$\$|\$[^$]*\$", re.S)


def _questions_error(question: str) -> str | None:
    asked = len(re.findall(r"[?؟]", CODE_OR_MATH.sub("", question)))
    if asked <= 1:
        return None
    return (
        f"error: not shown. A quick check asks one thing; this one asks {asked} questions. "
        "Pose the first now as its own check, and the others as further checks, one per turn"
    )


def _choice_error(lesson: dict, kind: str, answer_key: str, options: list[str], misconceptions: dict[str, str]) -> str | None:
    if misconceptions and (kind != "choice" or not set(misconceptions) <= set(options) - {answer_key}):
        return "error: misconceptions maps wrong options of a choice quiz, each exactly as written, to the belief behind it"
    most = PLACEMENT_OPTIONS if lesson["phase"] == "placement" else 5
    if kind == "choice" and not (2 <= len(options) <= most and answer_key in options):
        return f"error: a choice quiz needs 2 to {most} options here, one of them exactly equal to answer_key"
    return None


def _quiz_error(
    lesson: dict, question: str, kind: str, answer_key: str, options: list[str], misconceptions: dict[str, str],
    number: int | None, lemma: str, pretest: bool,
) -> str | None:
    if problem := _choice_error(lesson, kind, answer_key, options, misconceptions):
        return problem
    if number and number > lesson["questions"]:
        return f"error: the placement check has {lesson['questions']} questions and all are posed; call set_placement"
    if lemma and not lesson["lang"]:
        return "error: lemma needs a language course; pose_vocab_check or add_reading sets the language"
    if problem := _questions_error(question):
        return problem
    if pretest and not prepared(lesson) and (problem := _pretest_length_error("\n".join([question, *options]))):
        return problem
    return None


def _quiz_card(
    lesson: dict, question: str, kind: str, options: list[str], answer_key: str, explanation: str, lemma: str, pretest: bool,
    translation: str, misconceptions: dict[str, str],
) -> int:
    card_id = db.add_card(
        lesson["course_id"], None if pretest else lesson["concept_id"], question, kind, options, answer_key, explanation,
        scheduled=lesson["phase"] != "placement" and not pretest and not prepared(lesson), translation=translation,
        misconceptions=misconceptions,
    )
    if lemma:
        lemma = simplemma.lemmatize(lemma, lang=lesson["lang"]).lower()
        db.conn.execute("UPDATE cards SET lemma = ?, lang = ? WHERE id = ?", (lemma, lesson["lang"], card_id))
    return card_id


def _quiz_shown(
    lesson: dict, card_id: int, kind: str, options: list[str], answer_key: str, explanation: str, pretest: bool, form: str,
    translation: str, misconceptions: dict[str, str], number: int | None,
) -> dict:
    shown = {"card_id": card_id, "kind": kind, "options": options, "answer": None, "pretest": pretest, "form": form.strip()}
    if translation:
        shown["translation"] = translation
    if number:
        shown.update({"number": number, "of": lesson["questions"]})
    if keyed(lesson):
        # Material for the teacher, or a card answered offline: the key, the explanation and the beliefs come with it.
        shown.update({"answer_key": answer_key, "explanation": explanation} | ({"misconceptions": misconceptions} if misconceptions else {}))
    return shown


def _show_quiz(lesson: dict, question: str, shown: dict) -> str:
    block = db.add_block(lesson["id"], "quiz", question, shown)
    _show(lesson, block)
    return f"shown as quiz {block['id']}; {'go on with the unit' if lesson['batch'] else 'end the turn and wait for the answer'}"


@mcp.tool()
async def pose_quiz(
    lesson_id: int,
    question: str,
    kind: Literal["choice", "open"],
    answer_key: str,
    explanation: str,
    options: list[str] | None = None,
    lemma: str = "",
    pretest: bool = False,
    form: str = "",
    translation: str = "",
    misconceptions: dict[str, str] | None = None,
) -> str:
    """Show a quick check that the learner answers together with how sure they are.

    question asks exactly one thing, in one short question the learner takes in at a glance. A check that
    would ask how, which and why is several checks: pose them one after another, one per turn.

    choice: 2 to 5 options, and answer_key is exactly the right option; the server grades it.
    The server shuffles the options, so none may refer to another by position or letter
    (no "both of the above", no "A and C").
    In the placement check a choice has 2 to 4 options: the card adds "I don't know" as the last one
    by itself, so never write such an option.
    open: no options, and answer_key is the model answer; you grade it with grade_quiz
    when the answer arrives. The learner sees answer_key and explanation only after grading.
    The question comes back later in spaced reviews, so it must make sense on its own.
    lemma: in a language course, the vocabulary word the question tests; the grade sets its ledger state.
    pretest: the opening attempt of a concept lesson; it measures prior knowledge, so it never comes back
    as a review and does not count toward mastery. It asks for something the learner can attempt, as
    the lesson rules say. form: for an opening, which of the lesson rules' forms this is.
    translation: when the question is written in the language being learned, what it asks in the learner's
    own language; the options stay as they are. The learner opens it under the question when they need it.
    misconceptions: for a choice, each wrong option that a plausible wrong belief leads to, mapped to that belief
    in a few words ("a heavier object falls faster"). Write the options so each wrong one comes from such a
    belief; a learner who picks it is told the belief, and it is kept in their error notebook.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    options = options or []
    translation = translation.strip()
    misconceptions = {o: b.strip() for o, b in (misconceptions or {}).items() if b.strip()}
    number = placement_posed(lesson_id) + 1 if lesson["questions"] else None
    if problem := _quiz_error(lesson, question, kind, answer_key, options, misconceptions, number, lemma, pretest):
        return problem
    options = _shuffled(options) if kind == "choice" else []
    card_id = _quiz_card(lesson, question, kind, options, answer_key, explanation, lemma, pretest, translation, misconceptions)
    shown = _quiz_shown(lesson, card_id, kind, options, answer_key, explanation, pretest, form, translation, misconceptions, number)
    return _show_quiz(lesson, question, shown)


def placement_posed(lesson_id: int) -> int:
    return db.row("SELECT COUNT(*) AS n FROM blocks WHERE lesson_id = ? AND kind = 'quiz'", lesson_id)["n"]


SORT_CATEGORIES = (2, 4)
SORT_ITEMS = (6, 12)


def _sort_error(categories: list[str], placed: list[dict]) -> str | None:
    if not (SORT_CATEGORIES[0] <= len(categories) <= SORT_CATEGORIES[1]) or len(set(categories)) != len(categories) or not all(categories):
        return f"error: a sort needs {SORT_CATEGORIES[0]} to {SORT_CATEGORIES[1]} distinct categories"
    return _sort_items_error(categories, placed)


def _sort_items_error(categories: list[str], placed: list[dict]) -> str | None:
    if not (SORT_ITEMS[0] <= len(placed) <= SORT_ITEMS[1]) or len({i["text"] for i in placed}) != len(placed) or not all(i["text"] for i in placed):
        return f"error: a sort needs {SORT_ITEMS[0]} to {SORT_ITEMS[1]} distinct items"
    if not all(i["category"] in categories for i in placed) or {i["category"] for i in placed} != set(categories):
        return "error: every item names one of the categories, and every category has at least one item"
    return None


@mcp.tool()
async def pose_sort(lesson_id: int, question: str, categories: list[str], items: list[SortItem], explanation: str) -> str:
    """Show a sorting check: the learner places each item into one of the categories, and the server grades it.

    For concepts that are told apart (kinds, cases, types, rules that apply or not). question: what to
    sort and what the categories mean, in Markdown. categories: 2 to 4 short names. items: 6 to 12 short
    texts, each with its right category; every category gets at least one. explanation: shown after
    grading, what tells the categories apart; it never says where an item goes. The card marks the
    misplaced items without naming their right category, and the result [event] lists them: show in chat
    one pair of items that tells the categories apart, then pose the misplaced ones again with pose_sort.
    The check comes back later in spaced reviews. End the turn after posing it.
    """
    lesson = db.lesson(lesson_id)
    if not lesson:
        return f"error: no lesson with id {lesson_id}"
    if not question.strip() or not explanation.strip():
        return "error: the question and the explanation are required"
    categories = [c.strip() for c in categories]
    placed = [{"text": i.text.strip(), "category": i.category.strip()} for i in items]
    if problem := _sort_error(categories, placed):
        return problem
    options = _shuffled(placed)
    card_id = db.add_card(
        lesson["course_id"], lesson["concept_id"], question.strip(), "sort", options, json.dumps(categories), explanation.strip(),
        scheduled=lesson["phase"] != "placement" and not prepared(lesson),
    )
    # The learner's copy of the items carries no category; the teacher's does.
    shown = {"card_id": card_id, "kind": "sort", "options": [{"text": o["text"]} for o in options], "categories": categories, "answer": None}
    if keyed(lesson):
        shown.update({"options": options, "answer_key": json.dumps(categories), "explanation": explanation.strip()})
    return _show_quiz(lesson, question.strip(), shown)


@mcp.tool()
async def grade_quiz(quiz_id: int, correct: bool, feedback: str, misconception: str = "") -> str:
    """Grade the learner's answer to an open quiz. Judge the substance against the model answer, not the wording.
    misconception: for a wrong answer, the belief that seems to produce it, in a few words, when the answer shows
    one; it is kept in the learner's error notebook. Leave it empty for a slip or a gap with no belief behind it."""
    block = db.block(quiz_id)
    if not block or block["kind"] != "quiz":
        return f"error: no quiz with id {quiz_id}"
    data = block["data"]
    if data["answer"] is None:
        return "refused: the learner has not answered yet"
    if data.get("correct") is not None:
        return "refused: this quiz is already graded"
    result = quiz.grade(data["answer_id"], correct, misconception)
    block = db.set_block_data(quiz_id, {**data, **result, "feedback": feedback})
    lesson = db.lesson(block["lesson_id"])
    _show(lesson, block, "block.updated")
    reteach = result["confident_miss"] and lesson["phase"] != "placement"
    return "graded; a confident miss: re-teach it now" if reteach else "graded"
