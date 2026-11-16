import hashlib
import json
import logging
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import app as application, db, registry, settings  # noqa: E402

TOKEN = "wsr_secret-token-value"
BUNDLE = b"PK-not-really-a-zip" * 1000


@pytest.fixture
def client():
    from starlette.testclient import TestClient

    return TestClient(application.app, base_url="http://127.0.0.1:8321", raise_server_exceptions=False)


@pytest.fixture
def stored(tmp_path, monkeypatch):
    """A published version whose bundle is in the store."""
    version_hash = hashlib.sha256(tmp_path.name.encode()).hexdigest()
    (tmp_path / f"{version_hash}.zip").write_bytes(BUNDLE)
    monkeypatch.setattr(application, "VERSIONS", tmp_path)
    db.conn.execute(
        "INSERT INTO versions (hash, course_id, number, topic, notes, licence, forkable, credits, setup, written, units, published) "
        "VALUES (?, NULL, 1, 'Registry', '', 'CC-BY-4.0', 1, '[]', '[]', 1, 1, '2026-01-01')", (version_hash,))
    yield version_hash
    db.conn.execute("DELETE FROM versions WHERE hash = ?", (version_hash,))


@pytest.fixture
def remote(monkeypatch):
    """A registry reached through a mock transport: what a test sets in `answers` is what each call gets."""
    seen, answers, reads = [], {}, []

    def handler(request: httpx.Request) -> httpx.Response:
        reads.append(request.extensions["timeout"]["read"])
        body = request.content
        seen.append((request.method, request.url.path, dict(request.headers), body))
        answer = answers.get((request.method, request.url.path.removeprefix("/registry/v1")))
        if isinstance(answer, Exception):
            raise answer
        return answer or httpx.Response(500)

    monkeypatch.setattr(registry, "URL", "https://registry.test/registry/v1")
    monkeypatch.setattr(registry, "TOKEN", TOKEN)
    monkeypatch.setattr(registry, "TRANSPORT", httpx.MockTransport(handler))
    return type("Remote", (), {"seen": seen, "answers": answers, "reads": reads})


def accept(remote, version_hash, status=201, listed=()):
    remote.answers[("GET", "/links")] = httpx.Response(200, json=list(listed))
    remote.answers[("PUT", f"/bundles/{version_hash}")] = httpx.Response(status, json={"hash": version_hash, "size": len(BUNDLE)})
    remote.answers[("POST", "/links")] = httpx.Response(201, json={"id": "abc_-123", "url": "https://registry.test/l/abc_-123"})


def test_push_streams_the_bundle_then_asks_for_a_link(remote, stored, tmp_path):
    accept(remote, stored)
    assert registry.push(stored, tmp_path / f"{stored}.zip") == "https://registry.test/l/abc_-123"
    (put, post) = remote.seen
    assert put[:2] == ("PUT", f"/registry/v1/bundles/{stored}") and put[3] == BUNDLE
    assert put[2]["authorization"] == f"Bearer {TOKEN}" and put[2]["content-type"] == "application/zip"
    assert put[2]["content-length"] == str(len(BUNDLE))
    assert post[:2] == ("POST", "/registry/v1/links") and json.loads(post[3]) == {"hash": stored}


def test_a_bundle_is_sent_in_chunks_not_read_whole(remote, stored, tmp_path, monkeypatch):
    sent = []
    original = registry._chunks
    monkeypatch.setattr(registry, "CHUNK", 4096)
    monkeypatch.setattr(registry, "_chunks", lambda path: (sent.append(chunk) or chunk for chunk in original(path)))
    accept(remote, stored)
    registry.push(stored, tmp_path / f"{stored}.zip")
    assert len(sent) == -(-len(BUNDLE) // 4096) > 1 and max(map(len, sent)) == 4096
    assert b"".join(sent) == BUNDLE == remote.seen[0][3]


def test_a_bundle_the_registry_already_has_still_gets_a_link(remote, stored, tmp_path):
    accept(remote, stored, status=200)
    assert registry.push(stored, tmp_path / f"{stored}.zip").endswith("/l/abc_-123")


def test_the_upload_may_wait_longer_than_other_calls(remote, stored, tmp_path):
    accept(remote, stored)
    registry.push(stored, tmp_path / f"{stored}.zip")
    assert remote.reads == [300, 15]
    assert registry.UPLOAD_TIMEOUT.read >= 300 and registry.TIMEOUT.read == 15


def test_links_are_listed_and_revoked(remote):
    listed = [{"id": "a", "url": "u", "hash": "h", "topic": "t", "created": "c", "revoked": None}]
    remote.answers[("GET", "/links")] = httpx.Response(200, json=listed)
    remote.answers[("DELETE", "/links/a")] = httpx.Response(204)
    assert registry.links() == listed
    registry.revoke("a")
    assert remote.seen[-1][:2] == ("DELETE", "/registry/v1/links/a")


def test_revoking_a_link_the_registry_forgot_succeeds(remote):
    remote.answers[("DELETE", "/links/a")] = httpx.Response(404, json={"detail": "no such link"})
    registry.revoke("a")
    remote.answers[("DELETE", "/links/a")] = httpx.Response(500)
    with pytest.raises(registry.RegistryError, match="answered with an error"):
        registry.revoke("a")


def live(link_id, version_hash, revoked=None):
    return {"id": link_id, "url": f"https://registry.test/l/{link_id}", "hash": version_hash, "topic": "t", "created": "2026-01-01T00:00:00Z", "revoked": revoked}


def test_sharing_reuses_the_newest_live_link_of_the_version(remote, stored, tmp_path):
    accept(remote, stored, listed=[live("gone", stored, "2026-02-01T00:00:00Z"), live("other", "f" * 64), live("new", stored), live("old", stored)])
    assert registry.share(stored, tmp_path / f"{stored}.zip") == "https://registry.test/l/new"
    assert [call[0] for call in remote.seen] == ["GET"]


def test_sharing_makes_a_link_only_when_none_is_live(remote, stored, tmp_path):
    accept(remote, stored, listed=[live("gone", stored, "2026-02-01T00:00:00Z"), live("other", "f" * 64)])
    assert registry.share(stored, tmp_path / f"{stored}.zip") == "https://registry.test/l/abc_-123"
    assert [call[0] for call in remote.seen] == ["GET", "PUT", "POST"]


@pytest.mark.parametrize("answer, message", [
    (httpx.Response(401, json={"detail": "bad token"}), registry.REFUSED),
    (httpx.Response(404, json={"detail": "no such bundle"}), registry.UNKNOWN),
    (httpx.Response(404, text="<html>"), registry.UNKNOWN),
    (httpx.Response(409, json={"detail": "hash differs"}), registry.BUNDLE_REFUSED),
    (httpx.Response(422, json={"detail": "not a bundle"}), registry.BUNDLE_REFUSED),
    (httpx.Response(422, json={"detail": [{"loc": ["body"]}]}), registry.BUNDLE_REFUSED),
    (httpx.Response(413, json={"detail": "the bundle is over 256 MiB"}), registry.TOO_LARGE),
    (httpx.Response(413, text="<html>"), registry.TOO_LARGE),
    (httpx.Response(429, json={"detail": "slow down"}, headers={"Retry-After": "1800"}), registry.LIMIT),
    (httpx.Response(403, json={"detail": "the account is suspended"}), registry.SUSPENDED),
    (httpx.Response(408, json={"detail": "upload too slow"}), registry.SLOW),
    (httpx.Response(500, text="boom"), registry.FAILED),
    (httpx.Response(503, text="down"), registry.FAILED),
    (httpx.ConnectError("boom https://registry.test"), registry.UNREACHABLE),
    (httpx.ReadTimeout("slow"), registry.UNREACHABLE),
    (httpx.InvalidURL("bad"), registry.BAD_URL),
])
def test_a_failing_registry_is_explained_by_a_fixed_message(remote, stored, tmp_path, answer, message):
    remote.answers[("PUT", f"/bundles/{stored}")] = answer
    with pytest.raises(registry.RegistryError) as raised:
        registry.push(stored, tmp_path / f"{stored}.zip")
    assert str(raised.value) == message and message in registry.MESSAGES


def test_a_refused_link_request_is_explained_too(remote, stored, tmp_path):
    accept(remote, stored)
    remote.answers[("POST", "/links")] = httpx.Response(404, json={"detail": "no such bundle"})
    with pytest.raises(registry.RegistryError) as raised:
        registry.push(stored, tmp_path / f"{stored}.zip")
    assert str(raised.value) == registry.UNKNOWN


def test_a_bundle_file_that_cannot_be_read_is_an_error(remote, stored, tmp_path):
    accept(remote, stored)
    for path in (tmp_path / "missing.zip", tmp_path):  # no file; a folder, which stats but cannot be opened
        with pytest.raises(registry.RegistryError) as raised:
            registry.push(stored, path)
        assert str(raised.value) == registry.BAD_FILE
    assert remote.seen == []


def test_an_unreadable_answer_is_an_error(remote, stored, tmp_path):
    accept(remote, stored)
    remote.answers[("POST", "/links")] = httpx.Response(201, text="not json")
    with pytest.raises(registry.RegistryError, match="cannot read"):
        registry.push(stored, tmp_path / f"{stored}.zip")
    for body in ({"not": "a list"}, ["not a link"]):
        remote.answers[("GET", "/links")] = httpx.Response(200, json=body)
        with pytest.raises(registry.RegistryError, match="cannot read"):
            registry.links()


@pytest.mark.parametrize("raw, kept", [
    ("https://registry.test/registry/v1/", "https://registry.test/registry/v1"),
    ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
    ("", ""),
    ("registry.test/registry/v1", ""),
    ("ftp://registry.test", ""),
    ("http://", ""),
    ("https://user:secret@registry.test", ""),
    ("https://secret@registry.test", ""),
    ("https://registry.test:notaport", ""),
])
def test_only_a_plain_http_address_without_credentials_is_used(raw, kept, caplog):
    assert registry._address(raw) == kept
    warned = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warned) == bool(raw and not kept)
    assert all("WISE_SCHOLAR_REGISTRY_URL" in w and raw not in w for w in warned)


def test_the_routes_share_list_and_revoke(client, remote, stored):
    assert client.get("/api/registry").json() == {"configured": True}
    accept(remote, stored)
    assert client.post(f"/api/versions/{stored}/share").json() == {"url": "https://registry.test/l/abc_-123"}
    remote.answers[("GET", "/links")] = httpx.Response(200, json=[{"id": "abc_-123"}])
    assert client.get("/api/registry/links").json() == [{"id": "abc_-123"}]
    remote.answers[("DELETE", "/links/abc_-123")] = httpx.Response(204)
    assert client.delete("/api/registry/links/abc_-123").status_code == 204
    remote.answers[("DELETE", "/links/abc_-123")] = httpx.Response(404, json={"detail": "no such link"})
    assert client.delete("/api/registry/links/abc_-123").status_code == 204


def test_sharing_a_version_twice_gives_the_same_link(client, remote, stored):
    accept(remote, stored, listed=[live("one", stored)])
    assert client.post(f"/api/versions/{stored}/share").json() == {"url": "https://registry.test/l/one"}
    assert [call[0] for call in remote.seen] == ["GET"]


def test_the_routes_answer_with_the_fixed_message(client, remote, stored):
    accept(remote, stored)
    remote.answers[("PUT", f"/bundles/{stored}")] = httpx.Response(401, json={"detail": "x"})
    refused = client.post(f"/api/versions/{stored}/share")
    assert refused.status_code == 502 and refused.json()["detail"] == registry.REFUSED
    remote.answers[("PUT", f"/bundles/{stored}")] = httpx.Response(422, json={"detail": "internal path /srv/secret"})
    assert client.post(f"/api/versions/{stored}/share").json()["detail"] == registry.BUNDLE_REFUSED
    remote.answers[("PUT", f"/bundles/{stored}")] = httpx.ConnectError("down")
    assert client.post(f"/api/versions/{stored}/share").json()["detail"] == registry.UNREACHABLE
    remote.answers[("GET", "/links")] = httpx.Response(500)
    assert client.get("/api/registry/links").json()["detail"] == registry.FAILED


def test_only_versions_kept_here_are_shared(client, remote, stored, tmp_path):
    other = "0" * 64
    (tmp_path / f"{other}.zip").write_bytes(BUNDLE)  # a file with no versions row
    ghost = "1" * 64
    db.conn.execute(
        "INSERT INTO versions (hash, course_id, number, topic, notes, licence, forkable, credits, setup, written, units, published) "
        "VALUES (?, NULL, 1, 'Ghost', '', 'CC-BY-4.0', 1, '[]', '[]', 1, 1, '2026-01-01')", (ghost,))  # a row with no file
    try:
        for bad in (other, ghost, "%2E%2E", "ABC", stored.upper(), stored[:63]):
            assert client.post(f"/api/versions/{bad}/share").status_code == 404, bad
    finally:
        db.conn.execute("DELETE FROM versions WHERE hash = ?", (ghost,))
    assert remote.seen == []
    assert client.delete("/api/registry/links/%2E%2E").status_code == 404
    assert client.delete("/api/registry/links/a b").status_code == 404
    assert remote.seen == []


def test_without_both_settings_the_feature_is_off(client, remote, stored, monkeypatch):
    for url, token in (("", TOKEN), ("https://registry.test/registry/v1", ""), ("", "")):
        monkeypatch.setattr(registry, "URL", url)
        monkeypatch.setattr(registry, "TOKEN", token)
        assert client.get("/api/registry").json() == {"configured": False}
        assert client.post(f"/api/versions/{stored}/share").status_code == 404
        assert client.get("/api/registry/links").status_code == 404
        assert client.delete("/api/registry/links/abc").status_code == 404
    assert remote.seen == []


def test_state_changes_keep_to_this_sites_own_pages(client, remote, stored):
    accept(remote, stored)
    remote.answers[("DELETE", "/links/abc")] = httpx.Response(204)
    cross = {"Origin": "https://evil.example"}
    assert client.post(f"/api/versions/{stored}/share", headers=cross).status_code == 403
    assert client.delete("/api/registry/links/abc", headers=cross).status_code == 403
    assert client.post(f"/api/versions/{stored}/share", headers={"Host": "evil.example"}).status_code == 421
    assert client.delete("/api/registry/links/abc", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert remote.seen == []
    same = {"Origin": "http://127.0.0.1:8321", "Sec-Fetch-Site": "same-origin"}
    assert client.post(f"/api/versions/{stored}/share", headers=same).status_code == 200


class Stub(BaseHTTPRequestHandler):
    """A registry over a real socket, so httpx and httpcore log as they do in production."""
    received: list = []

    def reply(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(200, b"[]")

    def do_PUT(self):
        Stub.received.append((self.headers["Authorization"], self.rfile.read(int(self.headers["Content-Length"]))))
        self.reply(201, b'{"hash": "h", "size": 1}')

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.reply(201, b'{"id": "a", "url": "http://registry.test/l/a"}')

    def log_message(self, *args):
        pass


def test_the_token_is_never_logged_at_any_level(client, remote, stored, caplog, monkeypatch):
    for name in ("", "httpx", "httpcore", "wise_scholar"):
        caplog.set_level(logging.DEBUG, logger=name)
    for answer in (httpx.ConnectError(f"cannot connect with {TOKEN}"), httpx.InvalidURL(TOKEN), httpx.Response(401, text=TOKEN),
                   httpx.Response(429, text=TOKEN, headers={"Retry-After": "60"}), httpx.Response(500, text=TOKEN),
                   httpx.Response(422, json={"detail": TOKEN})):
        remote.answers[("PUT", f"/bundles/{stored}")] = answer
        shown = client.post(f"/api/versions/{stored}/share")
        assert shown.status_code == 502 and TOKEN not in shown.text
    accept(remote, stored)
    assert client.post(f"/api/versions/{stored}/share").status_code == 200
    assert {r.name for r in caplog.records} >= {"httpx", "wise_scholar"}
    assert TOKEN not in caplog.text and all(TOKEN not in str(r.args) for r in caplog.records)

    monkeypatch.setitem(settings.STARTED, "WISE_SCHOLAR_REGISTRY_TOKEN", TOKEN)
    monkeypatch.setitem(settings.STARTED, "WISE_SCHOLAR_REGISTRY_URL", registry.URL)
    shown = client.get("/api/settings")
    assert TOKEN not in shown.text
    rows = {row["name"]: row for row in shown.json()["settings"]}
    assert rows["WISE_SCHOLAR_REGISTRY_TOKEN"]["value"] == "set" and not rows["WISE_SCHOLAR_REGISTRY_TOKEN"]["editable"]
    assert rows["WISE_SCHOLAR_REGISTRY_URL"]["value"] == registry.URL and not rows["WISE_SCHOLAR_REGISTRY_URL"]["editable"]


def test_the_token_stays_out_of_the_connection_traces_too(stored, tmp_path, caplog, monkeypatch):
    """httpcore's DEBUG traces run on a real socket; the code never turns them on, and with them on they hold no token."""
    server = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(registry, "URL", f"http://127.0.0.1:{server.server_port}/registry/v1")
    monkeypatch.setattr(registry, "TOKEN", TOKEN)
    Stub.received.clear()
    for name in ("", "httpx", "httpcore", "wise_scholar"):
        caplog.set_level(logging.DEBUG, logger=name)
    big = tmp_path / f"{stored}.zip"
    big.write_bytes(os.urandom(registry.CHUNK * 2 + 5))
    try:
        assert registry.push(stored, big) == "http://registry.test/l/a"
    finally:
        server.shutdown()
        server.server_close()
    assert Stub.received == [(f"Bearer {TOKEN}", big.read_bytes())]
    assert any(r.name.startswith("httpcore") for r in caplog.records)
    assert TOKEN not in caplog.text
