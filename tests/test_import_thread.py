import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from wise_scholar import app, bundle, db
from wise_scholar.routes import sharing as sharing_routes

# Only reached when a request never gets where the test expects it: a failure, never a wait the test relies on.
STUCK = 10
BASE = "http://127.0.0.1:8321"


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
    db.conn.execute("DELETE FROM profiles WHERE id > ?", (last,))


def _profile(who: str) -> int:
    return db.conn.execute("INSERT INTO profiles (name, mode) VALUES (?, 'learner')", (f"Import thread {who} {uuid4()}",)).lastrowid


def _written_course(profile: int) -> int:
    course = db.create_course("Gears", profile)["id"]
    for n, title in enumerate(("Teeth", "Ratios"), start=1):
        concept = db.conn.execute("INSERT INTO concepts (course_id, module, title, position) VALUES (?, 'Drives', ?, ?)", (course, title, n)).lastrowid
        lesson = db.create_lesson(course, title, "lesson", concept)
        db.add_block(lesson, "prose", f"On {title}.")
        db.add_block(lesson, "done", "", {})
    return course


def _bundle(client: TestClient, course: int) -> bytes:
    version = client.post(f"/api/courses/{course}/versions", json={}).json()["hash"]
    return client.get(f"/api/versions/{version}/bundle").content


def test_other_requests_are_answered_while_a_bundle_installs(places, monkeypatch):
    client = TestClient(app.app, base_url=BASE)
    zipped, reader = _bundle(client, _written_course(_profile("author"))), _profile("reader")
    installing, answered, real = threading.Event(), threading.Event(), bundle.install

    def install(*args, **kwargs):
        installing.set()
        answered.wait(STUCK)
        return real(*args, **kwargs)

    monkeypatch.setattr(bundle, "install", install)

    async def both():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url=BASE) as http:
            importing = asyncio.create_task(http.post(f"/api/import?profile={reader}", files={"file": ("v.zip", zipped)}))
            assert await asyncio.to_thread(installing.wait, STUCK)
            asked = await http.get("/api/profiles")
            import_done_first = importing.done()
            answered.set()
            return await importing, asked, import_done_first

    imported, asked, import_done_first = asyncio.run(both())
    assert asked.status_code == 200
    assert not import_done_first
    assert imported.status_code == 200, imported.text
    assert db.course(imported.json()["id"])["mode"] == "replay"


def test_a_newer_version_imported_beside_the_older_one_is_offered_on_its_course(places, monkeypatch):
    client = TestClient(app.app, base_url=BASE)
    course, reader = _written_course(_profile("author")), _profile("reader")
    first = _bundle(client, course)
    concept = db.conn.execute("INSERT INTO concepts (course_id, module, title, position) VALUES (?, 'Drives', 'Backlash', 3)", (course,)).lastrowid
    db.add_block(db.create_lesson(course, "Backlash", "lesson", concept), "done", "", {})
    second = _bundle(client, course)

    installing, waiting = threading.Event(), threading.Event()

    class Turn:
        lock = threading.Lock()

        def __enter__(self):
            if not self.lock.acquire(blocking=False):
                waiting.set()
                self.lock.acquire()

        def __exit__(self, *exc):
            self.lock.release()

    turn = Turn()

    class Turns(dict):
        def setdefault(self, key, default=None):
            return turn

    monkeypatch.setattr(sharing_routes, "_importing", Turns(), raising=False)  # missing on code that has no turns
    real = bundle.install

    def install(*args, **kwargs):
        installing.set()
        waiting.wait(STUCK)
        return real(*args, **kwargs)

    monkeypatch.setattr(bundle, "install", install)

    def send(zipped):
        return TestClient(app.app, base_url=BASE).post(f"/api/import?profile={reader}", files={"file": ("v.zip", zipped)})

    with ThreadPoolExecutor(2) as pool:
        older = pool.submit(send, first)
        assert installing.wait(STUCK)
        newer = pool.submit(send, second)
        older, newer = older.result(), newer.result()
    assert [older.status_code, newer.status_code] == [200, 200], [older.text, newer.text]
    assert newer.json()["id"] == older.json()["id"]
    assert newer.json()["upgrade"] == 2
    assert len(db.rows("SELECT 1 FROM courses WHERE profile_id = ?", reader)) == 1
