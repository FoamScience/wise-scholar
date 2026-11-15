import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from wise_scholar import app as application
from pywebpush import WebPushException
from requests import Response

from wise_scholar import db, remind

FCM = "https://fcm.googleapis.com/fcm/send/"
KEYS = {"p256dh": "BPk", "auth": "au"}
# 19:00 in Berlin on a winter day is 18:00 UTC
EVENING = datetime(2026, 11, 15, 18, 5, tzinfo=timezone.utc)


@pytest.fixture
def client():
    return TestClient(application.app, base_url="http://127.0.0.1:8321", raise_server_exceptions=False)


@pytest.fixture
def pushed(monkeypatch):
    """Stands in for the push services: records each payload and drops the endpoints listed in gone."""
    sent, gone = [], set()

    def push(subscription, payload):
        if subscription["endpoint"] in gone:
            return False
        sent.append((subscription["endpoint"], json.loads(payload)))
        return True

    monkeypatch.setattr(remind, "_push", push)
    return sent, gone


def _profile(at: str | None = "19:00", tz: str = "Europe/Berlin", locale: str = "en") -> int:
    return db.conn.execute(
        "INSERT INTO profiles (name, locale, remind_at, remind_tz) VALUES (?, ?, ?, ?)", (f"P {uuid4()}", locale, at, tz)
    ).lastrowid


def _device(profile: int) -> str:
    endpoint = FCM + uuid4().hex
    db.conn.execute(
        "INSERT INTO push_subscriptions (endpoint, profile_id, keys, origin) VALUES (?, ?, ?, ?)",
        (endpoint, profile, json.dumps(KEYS), "https://learn.example"),
    )
    return endpoint


def _tick(due: dict[int, int], now: datetime = EVENING) -> None:
    asyncio.run(remind.tick(lambda p: due.get(p, 0), 0.5, now))


def _studied(profile: int, when: str) -> None:
    course = db.create_course("German", profile)["id"]
    lesson = db.create_lesson(course, "Unit", "lesson")
    db.conn.execute("INSERT INTO messages (lesson_id, role, text, created) VALUES (?, 'learner', 'hi', ?)", (lesson, when))


def test_a_reminder_is_owed_from_the_local_time_once_a_day():
    profile = db.profile(_profile())
    assert remind.owed(profile, datetime(2026, 11, 15, 17, 59, tzinfo=timezone.utc)) is None
    assert remind.owed(profile, EVENING) == "2026-11-15"
    assert remind.owed({**profile, "reminded": "2026-11-15"}, EVENING) is None
    assert remind.owed({**profile, "reminded": "2026-11-15"}, datetime(2026, 11, 16, 18, 0, tzinfo=timezone.utc)) == "2026-11-16"


def test_due_reviews_ping_every_device_in_the_profiles_language_once(pushed):
    sent, _ = pushed
    profile = _profile(locale="fr")
    phone, laptop = _device(profile), _device(profile)
    _tick({profile: 12})
    _tick({profile: 12})
    assert {endpoint for endpoint, _ in sent} == {phone, laptop} and len(sent) == 2
    note = sent[0][1]
    assert note == {"title": "Révisions à faire : 12", "body": "Environ 6 min, rien d'étudié aujourd'hui.", "url": "/#/review"}


def test_no_ping_when_nothing_is_due_or_today_was_studied(pushed):
    sent, _ = pushed
    idle, busy = _profile(), _profile()
    _device(idle), _device(busy)
    _studied(busy, "2026-11-15 09:00:00")
    _tick({busy: 5})
    assert sent == []
    assert db.profile(idle)["reminded"] == db.profile(busy)["reminded"] == "2026-11-15"


def test_yesterdays_study_does_not_count_for_today(pushed):
    sent, _ = pushed
    profile = _profile()
    _device(profile)
    _studied(profile, "2026-11-14 21:00:00")
    _tick({profile: 3})
    assert len(sent) == 1


def test_late_evening_utc_study_counts_for_the_next_local_day(pushed):
    sent, _ = pushed
    profile = _profile()
    _device(profile)
    # 23:30 UTC on the 14th is 00:30 on the 15th in Berlin
    _studied(profile, "2026-11-14 23:30:00")
    _tick({profile: 3})
    assert sent == []


def test_a_server_down_long_past_the_time_lets_the_day_pass(pushed):
    sent, _ = pushed
    profile = _profile()
    _device(profile)
    _tick({profile: 3}, datetime(2026, 11, 15, 22, 0, tzinfo=timezone.utc))
    assert sent == [] and db.profile(profile)["reminded"] == "2026-11-15"


def _answered(status: int | None):
    def webpush(*args, **kwargs):
        if status is None:
            return None
        response = Response()
        response.status_code = status
        raise WebPushException("refused", response=response)
    return webpush


@pytest.mark.parametrize("status, stands", [(None, True), (410, False), (404, False), (500, True), (429, True)])
def test_only_a_gone_subscription_is_dropped(monkeypatch, status, stands):
    monkeypatch.setattr(remind, "webpush", _answered(status))
    subscription = {"endpoint": FCM + "x", "keys": json.dumps(KEYS), "origin": "https://learn.example"}
    assert remind._push(subscription, "{}") is stands


def test_the_server_key_is_owner_only_and_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(remind, "KEY_FILE", tmp_path / "vapid.pem")
    remind._vapid.cache_clear()
    key = remind.public_key()
    assert (tmp_path / "vapid.pem").stat().st_mode & 0o777 == 0o600
    remind._vapid.cache_clear()
    assert remind.public_key() == key and len(key) == 87
    remind._vapid.cache_clear()


def test_a_device_the_push_service_dropped_is_forgotten(pushed):
    _, gone = pushed
    profile = _profile()
    gone.add(_device(profile))
    kept = _device(profile)
    _tick({profile: 1})
    assert [r["endpoint"] for r in db.rows("SELECT endpoint FROM push_subscriptions WHERE profile_id = ?", profile)] == [kept]


def test_only_browser_push_services_are_accepted():
    assert remind.push_service(FCM + "abc")
    assert remind.push_service("https://web.push.apple.com/QG")
    assert remind.push_service("https://updates.push.services.mozilla.com/wpush/v2/x")
    assert not remind.push_service("http://fcm.googleapis.com/fcm/send/x")
    assert not remind.push_service("https://fcm.googleapis.com.evil.example/x")
    assert not remind.push_service("https://127.0.0.1:8321/api/profiles")


def test_a_time_already_past_today_first_reminds_tomorrow():
    assert remind.settled_on_save("19:00", "Europe/Berlin", EVENING) == "2026-11-15"
    assert remind.settled_on_save("20:00", "Europe/Berlin", EVENING) is None
    assert remind.settled_on_save(None, "Europe/Berlin", EVENING) is None


def test_setting_the_time_checks_the_zone(client):
    profile = _profile()
    assert client.post(f"/api/profiles/{profile}/remind", json={"at": "25:00", "tz": "Europe/Berlin"}).status_code == 422
    assert client.post(f"/api/profiles/{profile}/remind", json={"at": "07:30", "tz": "Mars/Base"}).status_code == 422
    view = client.post(f"/api/profiles/{profile}/remind", json={"at": "07:30", "tz": "Africa/Tunis"}).json()
    assert (view["remind_at"], view["remind_tz"]) == ("07:30", "Africa/Tunis")
    assert client.post(f"/api/profiles/{profile}/remind", json={"at": None, "tz": "Africa/Tunis"}).json()["remind_at"] is None


def test_a_device_subscribes_moves_with_its_profile_and_is_forgotten(client):
    first, second = _profile(), _profile()
    endpoint = FCM + uuid4().hex
    body = {"endpoint": endpoint, "keys": KEYS}
    assert client.post(f"/api/profiles/{first}/push", json={**body, "endpoint": "https://evil.example/x"}).status_code == 422
    assert client.post(f"/api/profiles/{first}/push", json=body, headers={"Origin": "http://127.0.0.1:8321"}).status_code == 204
    assert client.post("/api/push/device", json={"endpoint": endpoint}).json() == {"profile": first}
    # no Origin, as from a non-browser client: the address the request came to stands in
    local = TestClient(application.app, base_url="http://localhost:8321")
    assert local.post(f"/api/profiles/{second}/push", json=body).status_code == 204
    row = db.row("SELECT * FROM push_subscriptions WHERE endpoint = ?", endpoint)
    assert row["profile_id"] == second and json.loads(row["keys"]) == KEYS and row["origin"] == "http://localhost:8321"
    assert client.post("/api/push/device", json={"endpoint": endpoint}).json() == {"profile": second}
    assert client.post("/api/push/forget", json={"endpoint": endpoint}).status_code == 204
    assert client.post("/api/push/device", json={"endpoint": endpoint}).json() == {"profile": None}
    assert db.row("SELECT 1 FROM push_subscriptions WHERE endpoint = ?", endpoint) is None


def test_the_test_button_sends_a_test_note_not_a_reminder(client, pushed):
    sent, _ = pushed
    profile = _profile(at=None, locale="fr")
    _device(profile)
    assert client.post(f"/api/profiles/{profile}/remind/test").json() == {"sent": 1}
    assert sent[0][1]["body"] == "Les rappels arrivent sur cet appareil."
