"""An installed exercise keeps its author's starter files, so a replay shows its changes from them, and a version made
from the replay still ships them."""
import asyncio
import json
import uuid

from replays import import_version as _import, publish as _publish, shelf, who as _who  # noqa: F401

from wise_scholar import bundle, course_files, db
from wise_scholar.routes import sharing as sharing_routes
from wise_scholar.tools import practice

STARTERS = {"Loft": ("loft/blade.py", "def loft():\n    pass\n"), "Sweep": ("sweep/rail.py", "def sweep():\n    pass\n")}


def _authored() -> tuple[int, dict[str, int]]:
    """A prepared course of two finished units, each posing an exercise whose solution and hints are written; returns
    the course and each exercise's block by unit."""
    course = db.create_course(f"Blades {uuid.uuid4().hex[:6]}", _who("teacher"))["id"]
    db.conn.execute("UPDATE courses SET mode = 'teacher' WHERE id = ?", (course,))
    db.set_concepts(course, [{"title": "Blades", "concepts": list(STARTERS), "known": []}])
    exercises = {}
    for unit, (path, content) in STARTERS.items():
        concept = next(c["id"] for c in db.concepts(course) if c["title"] == unit)
        lesson = db.create_lesson(course, unit, "lesson", concept)
        files = [practice.ExerciseFile(path=path, content=content)]
        assert asyncio.run(practice.pose_exercise(lesson, f"{unit} it.", files, f"python {path}")).startswith("shown")
        [block] = [b for b in db.blocks(lesson) if b["kind"] == "exercise"]
        db.set_block_data(block["id"], {**block["data"], "hints": [f"HINTKEY {unit}"], "solution": f"SOLKEY {unit}"})
        db.add_block(lesson, "done", f"You can {unit.lower()}.", {})
        exercises[unit] = block["id"]
    return course, exercises


def _exercises(course: int) -> dict[str, dict]:
    return {b["title"]: {**b, "data": json.loads(b["data"])} for b in db.rows(
        "SELECT b.*, l.title FROM blocks b JOIN lessons l ON l.id = b.lesson_id WHERE l.course_id = ? AND b.kind = 'exercise'", course,
    )}


def _workspace(course: int):
    return db.WORKSPACE / db.course(course)["slug"]


def test_an_installed_exercise_starts_from_its_authors_files_without_its_solution(shelf):
    course, _ = _authored()
    replay = _import(_publish(course), _who())["id"]
    path, content = STARTERS["Loft"]
    course_files.write_text(_workspace(replay), path, "def loft():\n    return 'my own try'\n")
    loft = _exercises(replay)["Loft"]
    assert loft["data"]["starter"] == {path: content}
    assert bundle._starters({"data": json.dumps(loft["data"])}, _workspace(replay)) == ({path: content}, [])
    assert "SOLKEY" not in json.dumps(loft["data"]) and "HINTKEY" not in json.dumps(loft["data"])
    assert db.locked(loft["id"])["solution"] == "SOLKEY Loft"


def test_a_version_made_from_a_replay_ships_the_starters_it_came_with_and_hashes_as_without_them(shelf):
    course, _ = _authored()
    replay = _import(_publish(course), _who())["id"]
    fork, _, _ = bundle.build(replay, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], source_dir=_workspace(replay))
    assert all("starter" not in (b["data"] or {}) for x in fork["lessons"] for b in x["blocks"])
    for b in _exercises(replay).values():
        db.set_block_data(b["id"], {k: v for k, v in b["data"].items() if k != "starter"})
    bare, _, _ = bundle.build(replay, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], source_dir=_workspace(replay))
    assert [u["hash"] for u in fork["units"]] == [u["hash"] for u in bare["units"]]
    assert fork["files"] == bare["files"]

    course_files.write_text(_workspace(replay), STARTERS["Loft"][0], "def loft():\n    return 'my own try'\n")
    for b in _exercises(replay).values():
        db.set_block_data(b["id"], {**b["data"], "starter": dict([STARTERS[b["title"]]])})
    edited, _, _ = bundle.build(replay, notes="", licence="CC-BY-SA-4.0", forkable=True, sources=[], source_dir=_workspace(replay))
    assert edited["files"] == bare["files"]


def test_an_upgrade_gives_a_restarted_unit_its_new_starters_and_a_kept_one_keeps_what_it_had(shelf):
    course, exercises = _authored()
    replay = _import(_publish(course), _who())["id"]
    before = _exercises(replay)
    db.set_block_data(before["Loft"]["id"], {k: v for k, v in before["Loft"]["data"].items() if k != "starter"})
    path = STARTERS["Sweep"][0]
    sweep = db.block(exercises["Sweep"])
    db.set_block_data(sweep["id"], {**sweep["data"], "starter": {path: "def sweep(rail):\n    pass\n"}})
    db.conn.execute("UPDATE blocks SET markdown = 'Sweep it along a rail.' WHERE id = ?", (sweep["id"],))  # the starter alone is not the unit's
    course_files.write_text(_workspace(course), path, "def sweep(rail):\n    pass\n")
    version = _publish(course)
    done = sharing_routes.upgrade_course(replay, sharing_routes.Upgrade(hash=version))["upgraded"]
    assert (len(done["kept"]), len(done["restarted"])) == (1, 1)
    after = _exercises(replay)
    assert "starter" not in after["Loft"]["data"]
    assert after["Sweep"]["data"]["starter"] == {path: "def sweep(rail):\n    pass\n"}
    assert "SOLKEY" not in json.dumps(after["Sweep"]["data"])
