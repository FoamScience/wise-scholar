import json
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.etree import ElementTree as ET

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

from .. import app as core
from .. import crafted, db, handwork, hub, speech
from ..app import CLIP_LIMIT, _add_photo, _handwork_block, _pending_photos, _profile, app, log


@app.get("/api/tts")
async def text_to_speech(text: str, lang: str) -> FileResponse:
    if not 0 < len(text) <= 600:
        raise HTTPException(422, "one sentence or paragraph at a time, up to 600 characters")
    try:
        return FileResponse(await speech.tts(text.strip(), lang), media_type="audio/wav")
    except RuntimeError as e:
        log.warning("tts failed: %s", e)
        raise HTTPException(503, str(e)) from None


@app.get("/api/figures/{block_id}.svg")
def figure_svg(block_id: int) -> Response:
    block = db.block(block_id)
    if not block or block["kind"] != "figure":
        raise HTTPException(404, "no such figure")
    svg = block["data"]["svg"]
    return Response(crafted.standalone(svg) if block["data"].get("crafted") else svg, media_type="image/svg+xml")


@app.get("/api/audio/podcasts/{name}")
async def podcast_audio(name: str) -> FileResponse:
    path = speech.AUDIO / "podcasts" / name
    if not (name.endswith(".opus") and name[:-5].isdigit() and path.exists()):
        raise HTTPException(404, "no such cast")
    return FileResponse(path, media_type="audio/ogg")


# a podcast app keeps what it downloaded; the feed lists only the newest
FEED_CASTS = 100


@app.get("/api/profiles/{profile_id}/casts.rss")
def cast_feed(profile_id: int, request: Request) -> Response:
    """The profile's ready casts as a podcast feed, newest first, so a podcast app can fetch and play them."""
    profile = _profile(profile_id)
    base = str(request.base_url).rstrip("/")
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = f"wise-scholar: {profile['name']}"
    ET.SubElement(channel, "link").text = base + "/"
    ET.SubElement(channel, "description").text = "Casts from your wise-scholar courses."
    for cast in db.rows(
        "SELECT b.id, b.markdown, b.data, b.created, c.topic FROM blocks b JOIN lessons l ON l.id = b.lesson_id "
        "JOIN courses c ON c.id = l.course_id WHERE c.profile_id = ? AND c.archived = 0 AND b.kind = 'podcast' "
        "AND json_extract(b.data, '$.status') = 'ready' ORDER BY b.id DESC LIMIT ?",
        profile_id, FEED_CASTS,
    ):
        data = json.loads(cast["data"])
        path = speech.AUDIO / "podcasts" / f"{cast['id']}.opus"
        if not path.exists():
            continue
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"{cast['topic']}: {cast['markdown']}"
        ET.SubElement(item, "guid", isPermaLink="false").text = f"wise-scholar-cast-{cast['id']}"
        created = datetime.fromisoformat(cast["created"]).replace(tzinfo=timezone.utc)
        ET.SubElement(item, "pubDate").text = format_datetime(created)
        ET.SubElement(item, "enclosure", url=f"{base}{data['audio']}", length=str(path.stat().st_size), type="audio/ogg")
        ET.SubElement(item, "description").text = "\n".join(f"{line['speaker']}: {line['text']}" for line in data["lines"])
    return Response(ET.tostring(rss, encoding="utf-8", xml_declaration=True), media_type="application/rss+xml")


@app.post("/api/stt")
async def speech_to_text(audio: UploadFile, lang: str | None = None) -> dict:
    data = await audio.read(CLIP_LIMIT + 1)
    if len(data) > CLIP_LIMIT:
        raise HTTPException(413, "recordings are limited to 25 MB")
    clip = speech.AUDIO / "stt" / f"{uuid.uuid4()}.webm"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(data)
    try:
        return await speech.stt(clip, lang)
    except RuntimeError as e:
        log.warning("stt failed: %s", e)
        raise HTTPException(503, str(e)) from None
    finally:
        clip.unlink(missing_ok=True)


@app.post("/api/sources/{source_id}/delete")
def delete_source(source_id: int) -> None:
    source = db.row("SELECT * FROM sources WHERE id = ?", source_id)
    if not source:
        raise HTTPException(404, "no such file")
    db.delete_source(source_id)
    for path in (core.SOURCES / str(source["course_id"])).glob(f"{source_id}-*"):
        path.unlink(missing_ok=True)
    hub.publish(source["course_id"], {"type": "source.removed", "id": source_id})


def _handed_block(token: str) -> dict:
    block_id = handwork.handed(token)
    if block_id is None:
        raise HTTPException(410, "this link has expired; show the QR code again on the card")
    return _handwork_block(block_id)


@app.get("/api/handoff/{token}")
def handed_card(token: str) -> dict:
    """What the phone page shows: the card's task and the photos waiting on it."""
    block = _handed_block(token)
    return {"block_id": block["id"], "kind": block["kind"], "markdown": block["markdown"], "photos": [p["name"] for p in _pending_photos(block)]}


@app.post("/api/handoff/{token}/photos")
async def add_handed_photo(token: str, file: UploadFile) -> dict:
    block = await _add_photo(_handed_block(token), file)
    return {"photos": [p["name"] for p in _pending_photos(block)]}
