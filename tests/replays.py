"""What the replay tests share: a test's own files and profiles, and a course published and imported through the routes."""
import asyncio
import io
import uuid

import pytest
from fastapi import UploadFile

from wise_scholar import app, db
from wise_scholar.routes import sharing as sharing_routes


@pytest.fixture
def shelf(tmp_path, monkeypatch):
    """Files land in the test's folder, the turns asked for are listed and none runs, and the profiles and courses made
    here leave the test database."""
    asked = []
    monkeypatch.setattr(db, "WORKSPACE", tmp_path / "workspace")
    monkeypatch.setattr(app, "SOURCES", tmp_path / "sources")
    monkeypatch.setattr(app, "VERSIONS", tmp_path / "versions")
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line, quiet=False, then=None: asked.append(line))
    last = db.row("SELECT COALESCE(MAX(id), 0) AS n FROM profiles")["n"]
    yield asked
    for c in db.rows("SELECT id FROM courses WHERE profile_id > ?", last):
        db.delete_course(c["id"])
    db.conn.execute("DELETE FROM versions")
    db.conn.execute("DELETE FROM profiles WHERE id > ?", (last,))


def who(mode: str = "learner") -> int:
    return db.conn.execute("INSERT INTO profiles (name, mode) VALUES (?, ?)", (f"Replay test {uuid.uuid4().hex}", mode)).lastrowid


def publish(course: int) -> str:
    return sharing_routes.publish_version(course, sharing_routes.Publish())["hash"]


def import_version(version: str, reader: int) -> dict:
    data = (app.VERSIONS / f"{version}.zip").read_bytes()
    return asyncio.run(sharing_routes.import_course(reader, UploadFile(io.BytesIO(data), filename="x.zip")))
