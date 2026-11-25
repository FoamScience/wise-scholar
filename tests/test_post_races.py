import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from wise_scholar import app, bundle, db
from wise_scholar.routes import courses as courses_routes, sharing as sharing_routes

# Only reached when a request never gets where the test expects it: a failure, never a wait the test relies on.
STUCK = 20


@pytest.fixture
def places(tmp_path, monkeypatch):
    for module, name in ((db, "WORKSPACE"), (app, "SOURCES"), (app, "VERSIONS")):
        monkeypatch.setattr(module, name, tmp_path / name.lower())
    monkeypatch.setattr(app, "_start_turn", lambda *a, **k: None)
    last = db.row("SELECT COALESCE(MAX(id), 0) AS n FROM profiles")["n"]
    yield
    for c in db.rows("SELECT id FROM courses WHERE profile_id > ?", last):
        db.delete_course(c["id"])
    db.conn.execute("DELETE FROM versions")
    db.conn.execute("DELETE FROM suggestions WHERE profile_id > ?", (last,))
    db.conn.execute("DELETE FROM profiles WHERE id > ?", (last,))


def _profile(who: str, mode: str = "learner") -> int:
    return db.conn.execute("INSERT INTO profiles (name, mode) VALUES (?, ?)", (f"Race {who} {uuid4()}", mode)).lastrowid


def _written_course(profile: int, units=("Pulleys", "Tension")) -> int:
    course = db.create_course("Belts", profile)["id"]
    for n, title in enumerate(units, start=1):
        concept = db.conn.execute("INSERT INTO concepts (course_id, module, title, position) VALUES (?, 'Drives', ?, ?)", (course, title, n)).lastrowid
        lesson = db.create_lesson(course, title, "lesson", concept)
        db.add_block(lesson, "prose", f"On {title}.")
        db.add_block(lesson, "done", "", {})
    return course


class Overlap:
    """Two requests held so both have read before either writes. Each stops at the first call of a function that reads
    (meet) until the other gets there too, unless the other waits for its turn on the route's lock of the course; the
    route's locks are replaced by one that lets both requests in first, so the second always finds the first holding it."""

    def __init__(self, monkeypatch, locks: tuple[object, str]):
        self.changed, self.arrived, self.met, self.waited = threading.Condition(), 0, 0, 0
        self.lock, self.mine = threading.Lock(), threading.local()
        overlap = self

        class Locks(dict):
            def setdefault(self, key, default=None):
                return overlap

        monkeypatch.setattr(*locks, Locks(), raising=False)  # missing on code that has no lock

    def acquire(self, blocking: bool = True) -> bool:
        if not getattr(self.mine, "arrived", False):
            self.mine.arrived = True
            with self.changed:
                self.arrived += 1
                self.changed.notify_all()
                assert self.changed.wait_for(lambda: self.arrived >= 2, timeout=STUCK)
        if self.lock.acquire(blocking=False):
            return True
        if not blocking:
            return False
        with self.changed:
            self.waited += 1
            self.changed.notify_all()
        return self.lock.acquire()

    def release(self) -> None:
        self.lock.release()

    def __enter__(self):
        self.acquire()

    def __exit__(self, *exc):
        self.release()

    def meet(self, monkeypatch, owner, name: str) -> None:
        real = getattr(owner, name)

        def met(*args, **kwargs):
            if not getattr(self.mine, "met", False):
                self.mine.met = True
                with self.changed:
                    self.met += 1
                    self.changed.notify_all()
                    assert self.changed.wait_for(lambda: self.met >= 2 or self.waited, timeout=STUCK)
            return real(*args, **kwargs)

        monkeypatch.setattr(owner, name, met)


def _both(*requests):
    """Two requests at once, each from its own client as two tabs would send them."""
    def send(request):
        client = TestClient(app.app, base_url="http://127.0.0.1:8321", raise_server_exceptions=False)
        return request(client)

    with ThreadPoolExecutor(len(requests)) as pool:
        return list(pool.map(send, requests))


def test_a_second_click_on_publish_gives_the_version_the_first_made(places, monkeypatch):
    course = _written_course(_profile("author"))
    overlap = Overlap(monkeypatch, (sharing_routes, "_publishing"))
    overlap.meet(monkeypatch, bundle, "build")
    publish = lambda client: client.post(f"/api/courses/{course}/versions", json={})
    answers = _both(publish, publish)
    assert [a.status_code for a in answers] == [200, 200], [a.text for a in answers]
    assert answers[0].json() == answers[1].json()
    assert answers[0].json()["number"] == 1
    assert len(db.rows("SELECT 1 FROM versions WHERE course_id = ?", course)) == 1
    assert overlap.waited == 1


def test_a_publish_that_waited_its_turn_checks_again_for_a_tutor_turn(places, monkeypatch):
    course = _written_course(_profile("author"))
    lesson = db.row("SELECT id FROM lessons WHERE course_id = ? AND concept_id IS NOT NULL", course)["id"]
    overlap = Overlap(monkeypatch, (sharing_routes, "_publishing"))
    real = bundle.publish

    def publish_while_a_turn_starts(*args, **kwargs):
        done = real(*args, **kwargs)
        monkeypatch.setitem(sharing_routes._turns, lesson, None)
        return done

    monkeypatch.setattr(bundle, "publish", publish_while_a_turn_starts)
    publish = lambda client: client.post(f"/api/courses/{course}/versions", json={})
    answers = _both(publish, publish)
    assert sorted(a.status_code for a in answers) == [200, 409]
    assert "wait for the tutor" in next(a.text for a in answers if a.status_code == 409)
    assert overlap.waited == 1


def test_duplicating_a_prepared_course_twice_at_once_makes_two_copies(places, monkeypatch):
    course = _written_course(_profile("teacher", "teacher"))
    overlap = Overlap(monkeypatch, (courses_routes, "_copying"))
    overlap.meet(monkeypatch, db, "_free_slug")
    duplicate = lambda client: client.post(f"/api/courses/{course}/duplicate")
    answers = _both(duplicate, duplicate)
    assert [a.status_code for a in answers] == [200, 200], [a.text for a in answers]
    assert sorted(a.json()["topic"] for a in answers) == ["Belts (2)", "Belts (3)"]
    assert len({a.json()["slug"] for a in answers}) == 2
    assert overlap.waited == 1


def test_two_tabs_upgrading_a_replay_at_once_move_it_once(places, monkeypatch):
    author, reader = _profile("author"), _profile("reader")
    course = _written_course(author)
    client = TestClient(app.app, base_url="http://127.0.0.1:8321")
    first = client.post(f"/api/courses/{course}/versions", json={}).json()["hash"]
    mine = client.post(f"/api/import?profile={reader}", files={"file": ("v1.zip", client.get(f"/api/versions/{first}/bundle").content)}).json()["id"]
    concept = db.conn.execute("INSERT INTO concepts (course_id, module, title, position) VALUES (?, 'Drives', 'Wear', 3)", (course,)).lastrowid
    db.add_block(db.create_lesson(course, "Wear", "lesson", concept), "done", "", {})
    db.conn.execute("UPDATE blocks SET markdown = 'On pulleys, again.' WHERE markdown = 'On Pulleys.' AND lesson_id IN (SELECT id FROM lessons WHERE course_id = ?)", (course,))
    second = client.post(f"/api/courses/{course}/versions", json={}).json()["hash"]
    assert client.post(f"/api/import?profile={reader}", files={"file": ("v2.zip", client.get(f"/api/versions/{second}/bundle").content)}).json()["upgrade"] == 2

    overlap = Overlap(monkeypatch, (sharing_routes, "_upgrading"))
    overlap.meet(monkeypatch, bundle, "changes")
    upgrade = lambda client: client.post(f"/api/courses/{mine}/upgrade", json={"hash": second})
    answers = _both(upgrade, upgrade)
    assert [a.status_code for a in answers] == [200, 200], [a.text for a in answers]
    assert sorted(a.json()["upgraded"] is None for a in answers) == [False, True]
    assert [a.json()["source_version"] for a in answers] == [second, second]
    assert db.course(mine)["source_version"] == second
    assert [c["title"] for c in db.concepts(mine)] == ["Pulleys", "Tension", "Wear"]
    lessons = db.rows("SELECT concept_id FROM lessons WHERE course_id = ? AND concept_id IS NOT NULL", mine)
    assert sorted(r["concept_id"] for r in lessons) == sorted(c["id"] for c in db.concepts(mine))
    assert overlap.waited == 1


def _version(places_client) -> tuple[str, bytes]:
    course = _written_course(_profile("author"))
    version = places_client.post(f"/api/courses/{course}/versions", json={}).json()["hash"]
    return version, places_client.get(f"/api/versions/{version}/bundle").content


def _take_slug_between(monkeypatch, other: int) -> list[str]:
    """Between a free slug's read and its insert, another connection, which waits for no lock, writes a course with
    that slug; returns what came of each try."""
    real, tried = db._free_slug, []

    def free_slug(topic):
        slug = real(topic)
        other_connection = sqlite3.connect(db.DB_PATH, timeout=0, isolation_level=None)
        try:
            other_connection.execute("INSERT INTO courses (topic, slug, profile_id, started, mode) VALUES ('Other', ?, ?, 0, 'learner')", (slug, other))
            tried.append("written")
        except sqlite3.OperationalError as e:
            tried.append(str(e))
        finally:
            other_connection.close()
        return slug

    monkeypatch.setattr(db, "_free_slug", free_slug)
    return tried


@pytest.mark.parametrize("make", ["create", "suggestion", "duplicate", "import"])
def test_no_write_lands_between_reading_a_free_slug_and_taking_it(places, monkeypatch, make):
    client = TestClient(app.app, base_url="http://127.0.0.1:8321", raise_server_exceptions=False)
    learner, teacher = _profile("learner"), _profile("teacher", "teacher")
    prepared, (version, zipped) = _written_course(teacher), _version(client)
    suggestion = db.conn.execute(
        "INSERT INTO suggestions (profile_id, title, pitch, kind, builds_on) VALUES (?, 'Belts', 'p', 'deeper', '[]')", (learner,),
    ).lastrowid
    tried = _take_slug_between(monkeypatch, learner)
    made = {
        "create": lambda: client.post("/api/courses", json={"topic": "Belts", "profile_id": learner}),
        "suggestion": lambda: client.post(f"/api/suggestions/{suggestion}/start"),
        "duplicate": lambda: client.post(f"/api/courses/{prepared}/duplicate"),
        "import": lambda: client.post(f"/api/import?profile={learner}", files={"file": ("v.zip", zipped)}),
    }[make]()
    assert made.status_code == 200, made.text
    assert tried == ["database is locked"]


def test_recording_a_version_already_recorded_keeps_its_one_row(places):
    client = TestClient(app.app, base_url="http://127.0.0.1:8321")
    version, zipped = _version(client)
    _, manifest, _ = bundle.unpack(zipped)
    db.conn.execute("DELETE FROM versions WHERE hash = ?", (version,))
    bundle.record_version(version, manifest)
    bundle.record_version(version, manifest)
    assert len(db.rows("SELECT 1 FROM versions WHERE hash = ?", version)) == 1
