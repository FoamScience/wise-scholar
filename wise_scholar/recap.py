"""A finished course told back as a story: what was learned when, week by week, with the claims, the mistakes and
when they were put right, the projects built, the time spent and how sure the learner was against how often right."""

from datetime import date, timedelta

from . import db


def week(when: str) -> str:
    """The Monday of the week a time falls in, as YYYY-MM-DD."""
    day = date.fromisoformat(when[:10])
    return (day - timedelta(days=day.weekday())).isoformat()


def story(course_id: int, now: str) -> dict:
    course = db.course(course_id)
    units = db.concepts(course_id)
    lessons = db.rows(
        "SELECT l.id, l.concept_id, (SELECT MIN(b.created) FROM blocks b WHERE b.lesson_id = l.id AND b.kind = 'done') AS finished "
        "FROM lessons l WHERE l.course_id = ? AND l.concept_id IS NOT NULL ORDER BY l.id", course_id,
    )
    begun = {lesson["concept_id"] for lesson in lessons}
    before = [{"concept_id": u["id"], "title": u["title"], "module": u["module"]} for u in units if u["known"] and u["id"] not in begun]

    steps, step_of = [], {}
    for u in units:
        own = [lesson for lesson in lessons if lesson["concept_id"] == u["id"]]
        finished = min((lesson["finished"] for lesson in own if lesson["finished"]), default=None)
        if not finished:
            continue
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
        steps.append({
            "concept_id": u["id"], "title": u["title"], "module": u["module"], "kind": u["kind"], "finished": finished,
            "week": week(finished), "minutes": round(spent.total_seconds() / 60), "estimated": not timed,
            "checks": [{"confidence": c["confidence"], "correct": bool(c["correct"])} for c in checks],
            "claims": [], "mistakes": [], "milestone": None,
        })
    steps.sort(key=lambda s: s["finished"])
    for n, s in enumerate(steps):
        step_of[s["concept_id"]] = n
    lesson_step = {lesson["id"]: step_of.get(lesson["concept_id"]) for lesson in lessons}

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
    kept = {c["id"] for c in claims}
    edges = [
        e for e in db.rows("SELECT e.from_id, e.to_id, e.kind FROM claim_edges e JOIN claims c ON c.id = e.from_id WHERE c.profile_id = ?", course["profile_id"])
        if e["from_id"] in kept and e["to_id"] in kept
    ]

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

    projects = db.capstones(course_id)
    for k in projects:
        for m in k["milestones"]:
            if m["done"] and (n := step_of.get(m["concept_id"])) is not None:
                steps[n]["milestone"] = {"project": k["title"], "deliverable": m["deliverable"]}

    answers = [
        {"created": a["created"], "confidence": a["confidence"], "correct": bool(a["correct"])}
        for a in db.rows(
            "SELECT a.created, a.confidence, a.correct FROM answers a JOIN cards k ON k.id = a.card_id "
            "WHERE k.course_id = ? AND a.correct IS NOT NULL AND a.stated = 1 ORDER BY a.created, a.id", course_id,
        )
    ]
    first = db.row(
        "SELECT MIN(a.created) AS at FROM answers a JOIN cards k ON k.id = a.card_id WHERE k.course_id = ?", course_id
    )["at"] or (steps[0]["finished"] if steps else None)
    recap = db.recap(course_id) or {}
    held = sum(c["state"] in ("held", "fading") for c in claims)
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
        "stats": {
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
        },
        "narrative": recap.get("narrative"),
        "positions": recap.get("positions"),
    }


def outline(s: dict) -> str:
    """The story as lines for the tutor that writes its narrative."""
    claims = {c["id"]: c for c in s["claims"]}
    mistakes = {m["id"]: m for m in s["mistakes"]}
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
    for w in s["weeks"]:
        lines.append(f"[week {w}]")
        for step in (x for x in s["steps"] if x["week"] == w):
            right = sum(c["correct"] for c in step["checks"])
            lines.append(
                f"  [unit] {step['title']} ({step['module']}), finished {step['finished'][:10]}, {step['minutes']} min, "
                f"checks {right}/{len(step['checks'])} right"
            )
            lines += [f"    [claim, {claims[i]['state']}] {claims[i]['text']}" for i in step["claims"]]
            lines += [
                f"    [mistake] {mistakes[i]['prompt'][:200]} | {'put right ' + mistakes[i]['fixed'][:10] if mistakes[i]['fixed'] else 'put right' if mistakes[i]['put_right'] else 'still open'}"
                for i in step["mistakes"]
            ]
            if step["milestone"]:
                lines.append(f"    [project] {step['milestone']['project']}: {step['milestone']['deliverable']}")
    weak = [c for c in s["claims"] if c["state"] in ("shaky", "fading")]
    lines += [f"[still {c['state']}] {c['text']}" for c in weak[:20]]
    lines += [f"[open mistake] {m['prompt'][:200]}" for m in s["mistakes"] if not m["put_right"]][:20]
    return "\n".join(lines)
