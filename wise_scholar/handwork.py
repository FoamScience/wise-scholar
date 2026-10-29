"""Photos of work a learner did by hand, on paper, for a challenge or an exercise. A photo is turned upright, cut down
to a size the tutor reads well and kept as JPEG, so what is stored and shown is never the upload itself. A phone
reaches one card through a short-lived hand-off token shown as a QR code beside it."""
import io
import secrets
import shutil
import time
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from . import db

HANDWORK = db.DB_PATH.parent / "handwork"
PHOTO_BYTES = 25 * 1024**2
PIXELS = 60_000_000  # a larger decode is refused, so a crafted file cannot take the server's memory
LONGEST = 1600
QUALITY = 82
PENDING = 6  # photos waiting for the next attempt
HANDOFF_SECONDS = 15 * 60

_handoffs: dict[str, tuple[int, float]] = {}


class Unreadable(ValueError):
    """Not an image Pillow reads, or one too large to decode safely."""


def shrink(data: bytes) -> bytes:
    """The photo upright, at most LONGEST pixels on its longer side, as JPEG."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > PIXELS:
                raise Unreadable(f"{image.width}x{image.height} pixels")
            upright = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise Unreadable(str(e)) from None
    upright.thumbnail((LONGEST, LONGEST))
    out = io.BytesIO()
    upright.save(out, "JPEG", quality=QUALITY, optimize=True)
    return out.getvalue()


def folder(course_id: int) -> Path:
    return HANDWORK / str(course_id)


def path(course_id: int, block_id: int, name: str) -> Path | None:
    """Where a stored photo of the card is, or None for a name that is not one of its photos."""
    if not name.startswith(f"{block_id}-") or not name.endswith(".jpg") or "/" in name or "\\" in name:
        return None
    found = folder(course_id) / name
    return found if found.is_file() else None


def save(course_id: int, block_id: int, data: bytes) -> str:
    jpeg = shrink(data)
    name = f"{block_id}-{uuid.uuid4().hex[:12]}.jpg"
    folder(course_id).mkdir(parents=True, exist_ok=True)
    (folder(course_id) / name).write_bytes(jpeg)
    return name


def remove_course(course_id: int) -> None:
    shutil.rmtree(folder(course_id), ignore_errors=True)


def hand_off(block_id: int) -> tuple[str, int]:
    """A token that lets a phone send photos to this card for HANDOFF_SECONDS, and that time."""
    now = time.monotonic()
    for token, (_, until) in list(_handoffs.items()):
        if until < now:
            del _handoffs[token]
    token = secrets.token_urlsafe(18)
    _handoffs[token] = (block_id, now + HANDOFF_SECONDS)
    return token, HANDOFF_SECONDS


def handed(token: str) -> int | None:
    """The card a live token belongs to."""
    block_id, until = _handoffs.get(token, (None, 0.0))
    return block_id if until >= time.monotonic() else None
