import os

KINDS = ("challenge", "exercise", "speaking")
REVEAL_AFTER = 3
MAX_HINTS = 3
# WISE_SCHOLAR_HINTS=1 gives challenges and exercises a hint ladder; without it the tutor guides with questions in the
# chat. Writing and speaking tasks keep theirs: their rungs are the tutor's corrections.
HINTS = os.environ.get("WISE_SCHOLAR_HINTS") == "1"


def new(reveal_after: int = REVEAL_AFTER, max_hints: int | None = None) -> dict:
    """max_hints: the ladder's length; by default the server's, none unless hints are on."""
    return {
        "attempts": [],
        "hints": [],
        "gave_up": False,
        "solved": False,
        "solution": None,
        "reveal_after": reveal_after,
        "max_hints": (MAX_HINTS if HINTS else 0) if max_hints is None else max_hints,
    }


def variable(kind: str, data: dict) -> bool:
    """A task a practice unit may vary once it is solved: not itself a milestone, a transfer task or a variant."""
    return kind in ("challenge", "exercise") and not (data.get("milestone") or data.get("transfer") or data.get("variant_of"))


def is_open(data: dict) -> bool:
    return not data["solved"] and data["solution"] is None


def reveal_blocker(data: dict, locked: bool = True) -> str | None:
    """Why the solution may not be shown yet, or None when the gate is open; locked=False keeps only the
    already-shown check (a prepared course, where the solution is part of the material)."""
    if data["solution"] is not None:
        return "the solution is already shown"
    if not locked or data["gave_up"] or data["solved"] or len(data["attempts"]) >= data["reveal_after"]:
        return None
    left = data["reveal_after"] - len(data["attempts"])
    return (
        f"the solution is locked until the learner makes {left} more attempt(s) or gives up. "
        "Do not put the solution in chat, in a hint or in another block. Guide with a question or a hint instead"
    )


def solution_files(data: dict, given) -> dict[str, str]:
    """The solution's text of an exercise's files, for the exercise's own files only."""
    files = data.get("files")
    if not isinstance(given, dict) or not isinstance(files, list):
        return {}
    return {p: c for p, c in given.items() if p in files and isinstance(c, str)}


def hint_blocker(data: dict) -> str | None:
    if not is_open(data):
        return "this challenge is already closed"
    if not data["max_hints"]:
        return "this task has no hint ladder. Ask a guiding question in chat, or wait for another attempt or a give-up"
    if len(data["hints"]) >= data["max_hints"]:
        return "the hint ladder is used up. Ask a guiding question in chat, or wait for another attempt or a give-up"
    return None


def said(data: dict, attempt: int = -1) -> str:
    """What the learner answered in an attempt: what they typed, and how the photos of their paper work were read."""
    if not data["attempts"]:
        return ""
    index = attempt % len(data["attempts"])
    reading = data.get("transcripts", {}).get(str(index), {}).get("text", "")
    return "\n\n".join(part for part in (data["attempts"][index], reading) if part)
