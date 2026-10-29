import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image

from wise_scholar import app, challenge, db, handwork, search, tutor


def _photo(width: int, height: int, orientation: int = 1, kind: str = "JPEG") -> bytes:
    image = Image.new("RGB", (width, height), "white")
    exif = Image.Exif()
    exif[0x0112] = orientation
    out = io.BytesIO()
    image.save(out, kind, exif=exif)
    return out.getvalue()


def _upload(data: bytes) -> UploadFile:
    return UploadFile(io.BytesIO(data), filename="page.jpg")


def test_a_photo_is_turned_upright_cut_down_and_kept_as_jpeg():
    # orientation 6: the camera held sideways, the picture shown turned a quarter
    upright = Image.open(io.BytesIO(handwork.shrink(_photo(4000, 3000, orientation=6))))
    assert upright.format == "JPEG" and upright.size == (1200, 1600)
    assert Image.open(io.BytesIO(handwork.shrink(_photo(800, 600, kind="PNG")))).size == (800, 600)
    with pytest.raises(handwork.Unreadable):
        handwork.shrink(b"%PDF-1.7 not a photo")


def test_photos_go_with_the_next_attempt_and_the_tutor_sees_them(monkeypatch, tmp_path):
    monkeypatch.setattr(handwork, "HANDWORK", tmp_path)
    turns = []
    monkeypatch.setattr(app, "_start_turn", lambda lesson, line: turns.append(line))
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Paper')").lastrowid
    course = db.create_course("Integrals", who)["id"]
    lesson = db.create_lesson(course, "Substitution", "lesson")
    block = db.add_block(lesson, "challenge", "Integrate x·cos(x²).", challenge.new())["id"]

    first = asyncio.run(app.add_photo(block, _upload(_photo(1000, 1400))))["data"]["photos"][0]["name"]
    second = asyncio.run(app.add_photo(block, _upload(_photo(1000, 1400))))["data"]["photos"][1]["name"]
    assert [p["attempt"] for p in db.block(block)["data"]["photos"]] == [None, None]
    assert app.get_photo(block, first).media_type == "image/jpeg"
    with pytest.raises(HTTPException) as refused:
        app.get_photo(block, "../../wise-scholar.db")
    assert refused.value.status_code == 404
    left = asyncio.run(app.delete_photo(block, second))["data"]["photos"]
    assert [p["name"] for p in left] == [first] and not handwork.path(course, block, second)

    asyncio.run(app.attempt(block, app.Answer(answer="")))
    assert db.block(block)["data"]["attempts"] == [""] and db.block(block)["data"]["photos"][0]["attempt"] == 0
    assert f"call view_handwork({block})" in turns[-1]
    with pytest.raises(HTTPException) as empty:
        asyncio.run(app.attempt(block, app.Answer(answer=" ")))
    assert empty.value.status_code == 422
    with pytest.raises(HTTPException) as sent:
        asyncio.run(app.delete_photo(block, first))
    assert sent.value.status_code == 404

    seen = asyncio.run(tutor.view_handwork(block))
    assert seen[0].startswith("Attempt 1: 1 photo(s)") and seen[1].to_image_content().mime_type == "image/jpeg"
    assert asyncio.run(tutor.view_handwork(block, attempt=2))[0].startswith("error: attempt 2 came without photos")
    # through the MCP server, as the agent calls it: the photos arrive as image content
    from types import SimpleNamespace

    from wise_scholar import backends

    tutor.turn_started(db.lesson(lesson), "tok-paper")
    try:
        context = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers={backends.TURN_HEADER: "tok-paper"})))
        result = asyncio.run(tutor.mcp.call_tool("view_handwork", {"block_id": block}, context))
        assert [c.type for c in result.content] == ["text", "image"] and result.content[1].mime_type == "image/jpeg"
    finally:
        tutor.turn_ended(lesson)

    assert asyncio.run(tutor.transcribe_handwork(block, "Let $u = x^2$, so $du = 2x\\,dx$ and the integral is $\\sin(u)$.")) == (
        "recorded; the learner sees it under their photos"
    )
    data = db.block(block)["data"]
    assert data["transcripts"]["0"]["by"] == "tutor" and challenge.said(data).startswith("Let $u = x^2$")
    assert asyncio.run(tutor.give_hint(block, "Check the factor in front.", ["$\\sin(u)$"])).startswith("shown as hint 1")
    assert search.search(course, "integral", 3, ("card",))[0]["ref"] == str(block)

    turns.clear()
    corrected = asyncio.run(app.correct_reading(block, 0, app.Reading(text="Let $u = x^2$; the integral is $\\sin(u)/2$.")))
    assert corrected["data"]["transcripts"]["0"] == {"text": "Let $u = x^2$; the integral is $\\sin(u)/2$.", "by": "learner"}
    assert "corrected how you read their paper work for attempt 1" in turns[-1]
    assert asyncio.run(tutor.transcribe_handwork(block, "something else")).startswith("refused: the learner corrected")
    with pytest.raises(HTTPException) as unread:
        asyncio.run(app.correct_reading(block, 3, app.Reading(text="x")))
    assert unread.value.status_code == 404

    asyncio.run(app.attempt(block, app.Answer(answer="sin(x²)/2 + C")))
    assert "view_handwork" not in turns[-1]

    for _ in range(handwork.PENDING):
        asyncio.run(app.add_photo(block, _upload(_photo(200, 200))))
    with pytest.raises(HTTPException) as full:
        asyncio.run(app.add_photo(block, _upload(_photo(200, 200))))
    assert full.value.status_code == 409


def test_a_phone_sends_photos_to_one_card_until_its_link_expires(monkeypatch, tmp_path):
    monkeypatch.setattr(handwork, "HANDWORK", tmp_path)
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Phone')").lastrowid
    course = db.create_course("Satzbau", who)["id"]
    lesson = db.create_lesson(course, "Nebensätze", "lesson")
    block = db.add_block(lesson, "challenge", "Schreib drei Sätze mit weil.", challenge.new())["id"]

    token = asyncio.run(app.hand_off(block))["token"]
    assert app.handed_card(token)["markdown"] == "Schreib drei Sätze mit weil." and app.handed_card(token)["photos"] == []
    assert len(asyncio.run(app.add_handed_photo(token, _upload(_photo(900, 1200))))["photos"]) == 1
    with pytest.raises(HTTPException) as bad:
        asyncio.run(app.add_handed_photo(token, _upload(b"not an image")))
    assert bad.value.status_code == 422

    monkeypatch.setattr(handwork.time, "monotonic", lambda: float("inf"))
    with pytest.raises(HTTPException) as gone:
        app.handed_card(token)
    assert gone.value.status_code == 410

    app.delete_course(course)
    assert not (tmp_path / str(course)).exists()
