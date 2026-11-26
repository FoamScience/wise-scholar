import os
import tempfile

import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import db, obsidian, quiz  # noqa: E402


def flashcards(course: int) -> list[str]:
    """The first line of each card in the unit note's flashcards."""
    vault = obsidian.Vault(course)
    lines = vault._flashcards(db.concepts(course)[0])
    return [card.split("\n")[0] for card in "\n".join(lines).split("\n#flashcards\n", 1)[1].strip().split("\n\n")] if lines else []


def answered_card(name: str, mode: str = "learner") -> tuple[int, int]:
    who = db.conn.execute("INSERT INTO profiles (name, mode, locale) VALUES (?, ?, 'en')", (name, mode)).lastrowid
    course = db.create_course(name, who)["id"]
    db.set_concepts(course, [{"title": "Hinges", "concepts": ["Pins"], "known": []}])
    unit = db.concepts(course)[0]["id"]
    card = db.add_card(course, unit, "Why a pin, a knuckle and a leaf?", "open", [], "Each holds the next.", "", scheduled=True)
    quiz.grade(quiz.submit(db.card(card), "no idea", 0.5), False)
    return course, card


def parts(n: int) -> list[dict]:
    return [{"question": f"Part {i}?", "kind": "open", "options": [], "answer_key": f"key {i}", "explanation": ""} for i in range(1, n + 1)]


@pytest.mark.parametrize("origin", ["short", "miss"])
def test_a_split_card_leaves_the_flashcards_once_one_of_its_parts_is_in_them(origin):
    course, card = answered_card(f"Vault split {origin}")
    first, second = db.split_card(card, parts(2), origin)
    assert flashcards(course) == ["Why a pin, a knuckle and a leaf?"]

    quiz.submit(db.card(first), "mine", 0.5)
    assert flashcards(course) == ["Part 1?"]
    quiz.submit(db.card(second), "mine", 0.5)
    assert flashcards(course) == ["Part 1?", "Part 2?"]


def test_a_part_split_again_gives_way_to_its_own_parts_and_takes_the_original_with_it():
    course, card = answered_card("Vault split twice")
    first, _ = db.split_card(card, parts(2), "short")
    [inner] = db.split_card(first, parts(1), "short")
    assert flashcards(course) == ["Why a pin, a knuckle and a leaf?"]
    quiz.submit(db.card(inner), "mine", 0.5)
    assert flashcards(course) == ["Part 1?"]


def test_an_authors_vault_shows_the_parts_in_place_of_the_card_they_split():
    course, card = answered_card("Vault split author", mode="teacher")
    db.split_card(card, parts(2), "short")
    assert flashcards(course) == ["Part 1?", "Part 2?"]
