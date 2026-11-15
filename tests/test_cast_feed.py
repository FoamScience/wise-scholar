import json
from uuid import uuid4
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from wise_scholar import app as application
from wise_scholar import db, speech


@pytest.fixture
def client():
    return TestClient(application.app, base_url="https://127.0.0.1:8321", raise_server_exceptions=False)


@pytest.fixture
def audio(tmp_path, monkeypatch):
    monkeypatch.setattr(speech, "AUDIO", tmp_path)
    (tmp_path / "podcasts").mkdir()
    return tmp_path / "podcasts"


def _cast(lesson: int, title: str, status: str = "ready") -> int:
    block = db.add_block(lesson, "podcast", title, {
        "lang": "de", "speakers": ["Anna", "Ben"], "lines": [{"speaker": "Anna", "text": "Hallo & willkommen"}],
        "glossary": [], "status": status, "done": 1, "audio": None, "starts": [0], "duration": 3.0, "cues": [],
    })["id"]
    data = db.block(block)["data"] | {"audio": f"/api/audio/podcasts/{block}.opus"}
    db.conn.execute("UPDATE blocks SET data = ? WHERE id = ?", (json.dumps(data), block))
    return block


def test_the_feed_lists_ready_casts_with_their_audio_newest_first(client, audio):
    profile = db.conn.execute("INSERT INTO profiles (name) VALUES (?)", (f"P {uuid4()}",)).lastrowid
    lesson = db.create_lesson(db.create_course("German B1", profile)["id"], "Unit", "lesson")
    older, newer, rendering, missing = _cast(lesson, "Im Café"), _cast(lesson, "Am Bahnhof"), _cast(lesson, "Draft", "rendering"), _cast(lesson, "Gone")
    for block in (older, newer, rendering):
        (audio / f"{block}.opus").write_bytes(b"x" * 10)

    response = client.get(f"/api/profiles/{profile}/casts.rss")
    assert response.content.startswith(b"<?xml version='1.0' encoding='utf-8'?>")
    rss = ET.fromstring(response.content)
    items = rss.findall("channel/item")
    assert [i.findtext("title") for i in items] == ["German B1: Am Bahnhof", "German B1: Im Café"]
    enclosure = items[0].find("enclosure").attrib
    assert enclosure == {"url": f"https://127.0.0.1:8321/api/audio/podcasts/{newer}.opus", "length": "10", "type": "audio/ogg"}
    assert items[0].findtext("description") == "Anna: Hallo & willkommen"
    assert missing not in {int(i.findtext("guid").rsplit("-", 1)[1]) for i in items}
    assert client.get("/api/profiles/999999/casts.rss").status_code == 404
