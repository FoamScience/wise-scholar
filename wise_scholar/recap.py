"""A finished course told back as a story: what was learned when, week by week, with the claims, the mistakes and
when they were put right, the projects built, the time spent and how sure the learner was against how often right."""

from datetime import date, timedelta

from . import db


def week(when: str) -> str:
    """The Monday of the week a time falls in, as YYYY-MM-DD."""
    day = date.fromisoformat(when[:10])
    return (day - timedelta(days=day.weekday())).isoformat()


def _known_before(course_id: int, units: list[dict]) -> list[dict]:
    placed = db.placed_out(course_id, units)
    return [{"concept_id": u["id"], "title": u["title"], "module": u["module"]} for u in units if u["id"] in placed]


def _edges(course: dict, claims: list[dict]) -> list[dict]:
    kept = {c["id"] for c in claims}
    return [
        e for e in db.rows("SELECT e.from_id, e.to_id, e.kind FROM claim_edges e JOIN claims c ON c.id = e.from_id WHERE c.profile_id = ?", course["profile_id"])
        if e["from_id"] in kept and e["to_id"] in kept
    ]


def _started(course_id: int, steps: list[dict]) -> str | None:
    return db.row(
        "SELECT MIN(a.created) AS at FROM answers a JOIN cards k ON k.id = a.card_id WHERE k.course_id = ?", course_id
    )["at"] or (steps[0]["finished"] if steps else None)


def _unit_step(u: dict, own: list[dict], finished: str) -> dict:
    spent, timed = timedelta(), True
    for lesson in own:
        took, measured = db.lesson_time(lesson["id"])
        spent += took
        timed = timed and measured
    ids = [lesson["id"] for lesson in own]
    marks = ", ".join("?" * len(ids))
    checks = db.rows(
        "SELECT DISTINCT a.id, a.confidence, a.correct FROM answers a JOIN blocks b ON json_extract(b.data, '$.card_id') = a.card_id "
        f"WHERE b.lesson_id IN ({marks}) AND a.correct IS NOT NULL AND a.stated = 1 AND a.created <= ? ORDER BY a.id",
        *ids, finished,
    )
    return {
        "concept_id": u["id"], "title": u["title"], "module": u["module"], "kind": u["kind"], "finished": finished,
        "week": week(finished), "minutes": round(spent.total_seconds() / 60), "estimated": not timed,
        "checks": [{"confidence": c["confidence"], "correct": bool(c["correct"])} for c in checks],
        "claims": [], "mistakes": [], "milestone": None,
    }


def _steps(units: list[dict], lessons: list[dict]) -> list[dict]:
    steps = []
    for u in units:
        own = [lesson for lesson in lessons if lesson["concept_id"] == u["id"]]
        finished = min((lesson["finished"] for lesson in own if lesson["finished"]), default=None)
        if not finished:
            continue
        steps.append(_unit_step(u, own, finished))
    steps.sort(key=lambda s: s["finished"])
    return steps


def _claims(course: dict, course_id: int, now: str, steps: list[dict], lesson_step: dict) -> list[dict]:
    states = db.claim_states(course["profile_id"], now)
    claims = []
    for c in db.rows(
        "SELECT c.id, c.text, c.created, MIN(s.lesson_id) AS lesson_id FROM claims c JOIN claim_sources s ON s.claim_id = c.id "
        "JOIN lessons l ON l.id = s.lesson_id WHERE l.course_id = ? AND c.wrong = 0 GROUP BY c.id ORDER BY c.created, c.id", course_id,
    ):
        n = lesson_step.get(c["lesson_id"])
        claims.append({"id": c["id"], "text": c["text"], "created": c["created"], "state": states.get(c["id"], "unseen"), "step": n})
        if n is not None:
            steps[n]["claims"].append(c["id"])
    return claims


def _mistakes(course_id: int, steps: list[dict], step_of: dict) -> list[dict]:
    mistakes = []
    for m in db.rows(
        "SELECT e.id, e.card_id, e.prompt, e.said, e.correct, e.created, e.resolved, k.concept_id FROM errors e "
        "LEFT JOIN cards k ON k.id = e.card_id WHERE e.course_id = ? ORDER BY e.created, e.id", course_id,
    ):
        fixed = db.fixed_at(m["card_id"], m["created"]) if m["card_id"] else None
        n = step_of.get(m["concept_id"])
        entry = {"id": m["id"], "prompt": m["prompt"], "said": m["said"], "correct": m["correct"], "created": m["created"],
                 "fixed": fixed, "put_right": bool(fixed or m["resolved"]), "step": n, "concept_id": m["concept_id"]}
        mistakes.append(entry)
        if n is not None:
            steps[n]["mistakes"].append(m["id"])
    return mistakes


def _milestones(projects: list[dict], steps: list[dict], step_of: dict) -> None:
    for k in projects:
        for m in k["milestones"]:
            if m["done"] and (n := step_of.get(m["concept_id"])) is not None:
                steps[n]["milestone"] = {"project": k["title"], "deliverable": m["deliverable"]}


def _answers(course_id: int) -> list[dict]:
    return [
        {"created": a["created"], "confidence": a["confidence"], "correct": bool(a["correct"])}
        for a in db.rows(
            "SELECT a.created, a.confidence, a.correct FROM answers a JOIN cards k ON k.id = a.card_id "
            "WHERE k.course_id = ? AND a.correct IS NOT NULL AND a.stated = 1 ORDER BY a.created, a.id", course_id,
        )
    ]


def _stats(units: list[dict], steps: list[dict], before: list[dict], projects: list[dict], claims: list[dict], mistakes: list[dict]) -> dict:
    held = sum(c["state"] in ("held", "fading") for c in claims)
    return {
        "minutes": sum(s["minutes"] for s in steps),
        "estimated": any(s["estimated"] for s in steps),
        "units_done": len(steps) + len(before),
        "units": len(units),
        "projects_done": sum(k["done"] == len(k["milestones"]) for k in projects),
        "projects": len(projects),
        "claims_held": held,
        "claims": len(claims),
        "mistakes_fixed": sum(m["put_right"] for m in mistakes),
        "mistakes": len(mistakes),
    }


def story(course_id: int, now: str) -> dict:
    course = db.course(course_id)
    units = db.concepts(course_id)
    lessons = db.rows(
        "SELECT l.id, l.concept_id, (SELECT MIN(b.created) FROM blocks b WHERE b.lesson_id = l.id AND b.kind = 'done') AS finished "
        "FROM lessons l WHERE l.course_id = ? AND l.concept_id IS NOT NULL ORDER BY l.id", course_id,
    )
    before = _known_before(course_id, units)

    steps = _steps(units, lessons)
    step_of = {s["concept_id"]: n for n, s in enumerate(steps)}
    lesson_step = {lesson["id"]: step_of.get(lesson["concept_id"]) for lesson in lessons}

    claims = _claims(course, course_id, now, steps, lesson_step)
    edges = _edges(course, claims)

    mistakes = _mistakes(course_id, steps, step_of)

    projects = db.capstones(course_id)
    _milestones(projects, steps, step_of)

    answers = _answers(course_id)
    first = _started(course_id, steps)
    recap = db.recap(course_id) or {}
    return {
        "course": {"id": course_id, "topic": course["topic"], "level": course["level"], "placement": course["placement"],
                   "cover": course["cover"] is not None, "cover_alt": course["cover_alt"]},
        "started": first,
        "finished": recap.get("finished"),
        "modules": list(dict.fromkeys(u["module"] for u in units)),
        "before": before,
        "steps": steps,
        "weeks": list(dict.fromkeys(s["week"] for s in steps)),
        "claims": claims,
        "edges": edges,
        "mistakes": mistakes,
        "answers": answers,
        "stats": _stats(units, steps, before, projects, claims, mistakes),
        "narrative": recap.get("narrative"),
        "positions": recap.get("positions"),
    }


def _unit_lines(step: dict, claims: dict, mistakes: dict) -> list[str]:
    right = sum(c["correct"] for c in step["checks"])
    lines = [
        f"  [unit] {step['title']} ({step['module']}), finished {step['finished'][:10]}, {step['minutes']} min, "
        f"checks {right}/{len(step['checks'])} right"
    ]
    lines += [f"    [claim, {claims[i]['state']}] {claims[i]['text']}" for i in step["claims"]]
    lines += [
        f"    [mistake] {mistakes[i]['prompt'][:200]} | {'put right ' + mistakes[i]['fixed'][:10] if mistakes[i]['fixed'] else 'put right' if mistakes[i]['put_right'] else 'still open'}"
        for i in step["mistakes"]
    ]
    if step["milestone"]:
        lines.append(f"    [project] {step['milestone']['project']}: {step['milestone']['deliverable']}")
    return lines


def _head_lines(s: dict) -> list[str]:
    st = s["stats"]
    lines = [
        f"[course] {s['course']['topic']} | level at the start: {s['course']['level'] or 'unknown'}",
        f"[dates] {s['started'][:10] if s['started'] else 'unknown'} to {s['finished'][:10] if s['finished'] else 'not finished'}",
        (
            f"[totals] {st['minutes'] / 60:.1f} active hours; {st['units_done']} of {st['units']} units; "
            f"{st['projects_done']} of {st['projects']} projects; {st['claims_held']} of {st['claims']} claims held; "
            f"{st['mistakes_fixed']} of {st['mistakes']} mistakes put right"
        ),
    ]
    if s["course"]["placement"]:
        lines.append(f"[placement] {s['course']['placement']}")
    if s["before"]:
        lines.append("[known before] " + "; ".join(u["title"] for u in s["before"]))
    return lines


def outline(s: dict) -> str:
    """The story as lines for the tutor that writes its narrative."""
    claims = {c["id"]: c for c in s["claims"]}
    mistakes = {m["id"]: m for m in s["mistakes"]}
    lines = _head_lines(s)
    for w in s["weeks"]:
        lines.append(f"[week {w}]")
        for step in (x for x in s["steps"] if x["week"] == w):
            lines += _unit_lines(step, claims, mistakes)
    weak = [c for c in s["claims"] if c["state"] in ("shaky", "fading")]
    lines += [f"[still {c['state']}] {c['text']}" for c in weak[:20]]
    lines += [f"[open mistake] {m['prompt'][:200]}" for m in s["mistakes"] if not m["put_right"]][:20]
    return "\n".join(lines)


# --- Revisit: what a finished course left shaky, gone over on the board ---------------------------------------------
REVISIT_ITEMS = 4
REVISIT_FIGURES = 3
OUTLINE_LABEL = 90


def revisit_items(s: dict) -> list[dict]:
    """What a revisit goes over, most pressing first: open mistakes, then shaky claims, then fading ones."""
    def unit(n: int | None) -> dict | None:
        return s["steps"][n] if n is not None else None

    mistakes = [{"kind": "mistake", "unit": unit(m["step"]), **m} for m in s["mistakes"] if not m["put_right"]]
    claims = [{"kind": c["state"], "unit": unit(c["step"]), **c} for state in ("shaky", "fading") for c in s["claims"] if c["state"] == state]
    return (mistakes + claims)[:REVISIT_ITEMS]


def revisit_outline(items: list[dict]) -> dict:
    """The revisit's outline: one step per item, each step knowing the claim or the mistake its check is on."""
    def label(item: dict) -> str:
        text = " ".join(((item["prompt"] if item["kind"] == "mistake" else item["text"]) or "").split())
        return text if len(text) <= OUTLINE_LABEL else text[: OUTLINE_LABEL - 1] + "…"

    return {
        "steps": [label(i) for i in items], "at": 0, "added": None, "cards": 2 * len(items) + 1,
        "items": [{"error": i["id"]} if i["kind"] == "mistake" else {"claim": i["id"]} for i in items],
    }


def revisits_done(course_id: int) -> int:
    """How many revisits of the course are finished; the recap's narrative is written again after each one."""
    return db.row(
        "SELECT COUNT(*) AS n FROM lessons l WHERE l.course_id = ? AND l.phase = 'revisit' "
        "AND EXISTS (SELECT 1 FROM blocks b WHERE b.lesson_id = l.id AND b.kind = 'done')", course_id,
    )["n"]


def _unit_figures(concept_id: int) -> list[str]:
    return [
        r["markdown"] for r in db.rows(
            "SELECT b.markdown FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE l.concept_id = ? AND b.kind = 'figure' "
            "AND b.markdown != '' ORDER BY b.id LIMIT ?", concept_id, REVISIT_FIGURES,
        )
    ]


def revisit_line(items: list[dict], untrusted) -> str:
    """The event that opens a revisit, one entry per item with the unit that taught it and the figures it showed."""
    lines = [
        "[event] The course is finished, and these items are still shaky. Go over them on the board, one per turn, in this "
        "order, as your instructions say."
    ]
    for n, item in enumerate(items, 1):
        if item["kind"] == "mistake":
            lines.append(f"{n}. [open mistake] Card: {(item['prompt'] or '')[:300]} | the learner answered: {untrusted(item['said'] or '')[:300]} | right: {(item['correct'] or '')[:300]}")
        else:
            lines.append(f"{n}. [claim, {item['kind']}] {item['text']}")
        if item["unit"]:
            shown = _unit_figures(item["unit"]["concept_id"])
            lines.append(f"   Taught in: {item['unit']['title']}." + (f" Its figures showed: {'; '.join(shown)}" if shown else " It showed no figure."))
    return "\n".join(lines)
