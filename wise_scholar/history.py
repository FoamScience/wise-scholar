RECENT_LESSONS = 6
LINE = 160


def _short(text: str) -> str:
    first = " ".join(text.split())
    return first if len(first) <= LINE else first[: LINE - 1] + "…"


def _outcome(data: dict) -> str:
    parts = ["solved" if data["solved"] else "gave up" if data["gave_up"] else "left open"]
    parts.append(f"{len(data['attempts'])} attempt(s)")
    if data["hints"]:
        parts.append(f"{len(data['hints'])} hint(s)")
    return ", ".join(parts)


def _line(block: dict) -> str:
    kind, data, text = block["kind"], block["data"] or {}, _short(block["markdown"])
    if kind == "quiz":
        if data.get("correct") is None:
            return f"quiz: {text} -> not answered"
        if data.get("unknown"):
            return f"quiz: {text} -> did not know"
        verdict = "right" if data["correct"] else "wrong"
        miss = " (confident miss)" if data.get("confident_miss") else ""
        return f"quiz: {text} -> {verdict} at {data['confidence']:.0%} sure{miss}"
    if kind == "exercise":
        return f"exercise ({', '.join(data['files'])}): {text} -> {_outcome(data)}"
    if kind == "challenge":
        return f"{'writing' if data.get('writing') else 'challenge'}: {text} -> {_outcome(data)}"
    if kind == "reading":
        return f"reading: {data['title']}"
    if kind == "done":
        return f"finished: {text}"
    return f"taught: {text}"


def digest(lessons: list[dict]) -> str:
    """What earlier concept lessons covered and how the learner did, for the start of a new lesson."""
    lines = []
    for lesson in lessons[-RECENT_LESSONS:]:
        lines.append(f"- {lesson['title']}:")
        lines += [f"  - {_line(b)}" for b in lesson["blocks"]] or ["  - opened, nothing done yet"]
    return "\n".join(lines)
