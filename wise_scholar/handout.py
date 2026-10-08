"""A unit's lesson plan as a hand-out: the teacher's copy with solutions, keys, hints and notes, or the students'
copy with the tasks and figures only. Markdown here; the PDF is the same page printed by the book machinery."""

from . import db, obsidian

STUDENT_KINDS = (*obsidian.CARD_KINDS, "figure")


def markdown(lesson_id: int, solutions: bool) -> str | None:
    lesson = db.lesson(lesson_id)
    if not lesson:
        return None
    vault = obsidian.Vault(lesson["course_id"], inline=True, solutions=solutions)
    full = next((l for l in vault.lessons if l["id"] == lesson_id), None)
    if full is None:
        return None
    pieces = vault.lesson_text(full, chat=False, kinds=None if solutions else STUDENT_KINDS)
    return f"# {lesson['title']}\n\n{lesson['topic']}\n\n" + "\n".join(pieces)
