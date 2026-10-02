KINDS = ("challenge", "exercise")
REVEAL_AFTER = 3
MAX_HINTS = 3


def new(reveal_after: int = REVEAL_AFTER) -> dict:
    return {
        "attempts": [],
        "hints": [],
        "gave_up": False,
        "solved": False,
        "solution": None,
        "reveal_after": reveal_after,
        "max_hints": MAX_HINTS,
    }


def is_open(data: dict) -> bool:
    return not data["solved"] and data["solution"] is None


def reveal_blocker(data: dict) -> str | None:
    """Why the solution may not be shown yet, or None when the gate is open."""
    if data["solution"] is not None:
        return "the solution is already shown"
    if data["gave_up"] or data["solved"] or len(data["attempts"]) >= data["reveal_after"]:
        return None
    left = data["reveal_after"] - len(data["attempts"])
    return (
        f"the solution is locked until the learner makes {left} more attempt(s) or gives up. "
        "Do not put the solution in chat, in a hint or in another block. Guide with a question or a hint instead"
    )


def hint_blocker(data: dict) -> str | None:
    if not is_open(data):
        return "this challenge is already closed"
    if len(data["hints"]) >= data["max_hints"]:
        return "the hint ladder is used up. Ask a guiding question in chat, or wait for another attempt or a give-up"
    return None
