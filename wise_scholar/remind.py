"""The daily review reminder: a Web Push to every device a profile turned it on from, once a day from the profile's
chosen local time, when reviews are due and nothing was studied that day."""
import asyncio
import json
import logging
import math
import os
from collections.abc import Callable
from datetime import datetime, time, timedelta
from functools import cache
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid, b64urlencode
from pywebpush import WebPushException, webpush

from . import db

log = logging.getLogger("wise_scholar")
KEY_FILE = db.DB_PATH.parent / "vapid.pem"
CHECK_SECONDS = 60
# a server down at the chosen time catches up only this long after it; later the day passes without a ping
LATE = timedelta(hours=3)
# a phone offline when the push is sent still gets it within the same day
TTL = 12 * 3600
# The browsers' push services; the server posts only to these, so a subscription cannot point it at another host.
PUSH_HOSTS = ("fcm.googleapis.com", "push.services.mozilla.com", "push.apple.com", "notify.windows.com")
URL = "/#/review"
TEXT = {
    "en": ("Reviews due: {due}", "About {minutes} min, nothing studied yet today."),
    "fr": ("Révisions à faire : {due}", "Environ {minutes} min, rien d'étudié aujourd'hui."),
    "ar": ("مراجعات مستحقة: {due}", "نحو {minutes} د، لم تدرس شيئًا اليوم بعد."),
}
TEST = {
    "en": ("wise-scholar", "Reminders reach this device."),
    "fr": ("wise-scholar", "Les rappels arrivent sur cet appareil."),
    "ar": ("wise-scholar", "تصل التذكيرات إلى هذا الجهاز."),
}


@cache
def _vapid() -> Vapid:
    if KEY_FILE.exists():
        return Vapid.from_file(str(KEY_FILE))
    vapid = Vapid()
    vapid.generate_keys()
    # created owner-only, so the private key is never readable by others, not even for a moment
    with os.fdopen(os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
        file.write(vapid.private_pem())
    return vapid


def public_key() -> str:
    """The server's key in the form PushManager.subscribe takes as applicationServerKey."""
    return b64urlencode(_vapid().public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))


def push_service(endpoint: str) -> bool:
    url = urlparse(endpoint)
    host = url.hostname or ""
    return url.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def message(locale: str, due: int, minutes_per_review: float) -> dict:
    title, body = TEXT.get(locale, TEXT["en"])
    return {"title": title.format(due=due), "body": body.format(minutes=max(1, math.ceil(due * minutes_per_review))), "url": URL}


def test_message(locale: str) -> dict:
    title, body = TEST.get(locale, TEST["en"])
    return {"title": title, "body": body, "url": "/"}


def settled_on_save(at: str | None, tz: str, now: datetime) -> str | None:
    """The `reminded` a newly saved time starts from: a time already past today first reminds tomorrow."""
    local = now.astimezone(ZoneInfo(tz))
    return local.date().isoformat() if at and local.time() >= time.fromisoformat(at) else None


def owed(profile: dict, now: datetime) -> str | None:
    """The profile's local date when its reminder is now owed and not yet settled, else None."""
    local = now.astimezone(ZoneInfo(profile["remind_tz"]))
    today = local.date().isoformat()
    if profile["reminded"] == today or local.time() < time.fromisoformat(profile["remind_at"]):
        return None
    return today


def _push(subscription: dict, payload: str) -> bool:
    """Whether the subscription still stands: the push service answers 404 or 410 for one the browser dropped."""
    try:
        webpush(
            {"endpoint": subscription["endpoint"], "keys": json.loads(subscription["keys"])},
            payload,
            vapid_private_key=_vapid(),
            vapid_claims={"sub": subscription["origin"]},
            ttl=TTL,
            timeout=30,
        )
    except WebPushException as e:
        if e.response is not None and e.response.status_code in (404, 410):
            return False
        log.warning("reminder push failed: %s", e)
    except requests.RequestException as e:
        log.warning("reminder push failed: %s", e)
    return True


async def send(profile_id: int, note: dict) -> int:
    """Pushes the note to the profile's devices; returns how many took it."""
    payload, sent = json.dumps(note), 0
    for subscription in db.rows("SELECT * FROM push_subscriptions WHERE profile_id = ?", profile_id):
        if await asyncio.to_thread(_push, subscription, payload):
            sent += 1
        else:
            db.conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (subscription["endpoint"],))
    return sent


async def _remind(profile: dict, due: Callable[[int], int], minutes_per_review: float, now: datetime) -> None:
    today = owed(profile, now)
    if not today:
        return
    # settled before sending: a send that fails is logged, never retried into a second ping
    db.conn.execute("UPDATE profiles SET reminded = ? WHERE id = ?", (today, profile["id"]))
    zone = ZoneInfo(profile["remind_tz"])
    start = datetime.combine(now.astimezone(zone).date(), time.fromisoformat(profile["remind_at"]), zone)
    last = db.last_activity(profile["id"])
    if now - start > LATE or (last and last.astimezone(zone).date().isoformat() == today):
        return
    if n := due(profile["id"]):
        await send(profile["id"], message(profile["locale"], n, minutes_per_review))


async def tick(due: Callable[[int], int], minutes_per_review: float, now: datetime) -> None:
    for profile in db.rows("SELECT * FROM profiles WHERE remind_at IS NOT NULL"):
        try:
            await _remind(profile, due, minutes_per_review, now)
        except Exception:
            log.exception("reminder of profile %s", profile["id"])


async def forever(due: Callable[[int], int], minutes_per_review: float) -> None:
    while True:
        try:
            await tick(due, minutes_per_review, datetime.now().astimezone())
        except Exception:
            log.exception("reminders")
        await asyncio.sleep(CHECK_SECONDS)
