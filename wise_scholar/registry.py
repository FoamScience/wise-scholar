"""A course registry the owner points this server at: published version bundles pushed there and shared by link.
Off unless WISE_SCHOLAR_REGISTRY_URL and WISE_SCHOLAR_REGISTRY_TOKEN are both set, the address as http(s) with no
credentials in it. The registry's own error text is never passed on, so every message is one the interface translates."""
import logging
import os
import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("wise_scholar")


def _address(raw: str) -> str:
    """The address when it is usable and carries no userinfo (it appears in logs); "" with one warning otherwise."""
    raw = raw.rstrip("/")
    try:
        parts = urlsplit(raw)
        usable = parts.scheme in ("http", "https") and bool(parts.hostname) and "@" not in parts.netloc and parts.port != 0
    except ValueError:
        usable = False
    if raw and not usable:
        log.warning("WISE_SCHOLAR_REGISTRY_URL must be an http or https address with a host and no user or password: course sharing is off")
    return raw if usable else ""


URL = _address(os.environ.get("WISE_SCHOLAR_REGISTRY_URL", ""))
TOKEN = os.environ.get("WISE_SCHOLAR_REGISTRY_TOKEN", "")
TIMEOUT = httpx.Timeout(15)
UPLOAD_TIMEOUT = httpx.Timeout(300, connect=15)  # the registry validates the whole bundle before it answers
CHUNK = 1 << 20
LINK_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
TRANSPORT: httpx.BaseTransport | None = None  # tests only

REFUSED = "the registry token was refused"
UNKNOWN = "the registry does not know this address or bundle"
BUNDLE_REFUSED = "the registry refused this bundle"
TOO_LARGE = "the bundle is too large for the registry, or your registry storage is full"
LIMIT = "the registry's push limit is reached; try again later"
SUSPENDED = "the registry refuses pushes from this account while it is suspended"
SLOW = "the upload to the registry took too long; try again"
FAILED = "the registry answered with an error; try again later"
UNREACHABLE = "the registry cannot be reached"
BAD_URL = "the registry address in the settings is not valid"
BAD_FILE = "the bundle file cannot be read"
UNREADABLE = "the registry answered something this app cannot read"
MESSAGES = (REFUSED, UNKNOWN, BUNDLE_REFUSED, TOO_LARGE, LIMIT, SUSPENDED, SLOW, FAILED, UNREACHABLE, BAD_URL, BAD_FILE, UNREADABLE)
ANSWERS = {401: REFUSED, 404: UNKNOWN, 409: BUNDLE_REFUSED, 422: BUNDLE_REFUSED, 413: TOO_LARGE, 429: LIMIT, 403: SUSPENDED, 408: SLOW}


class RegistryError(Exception):
    pass


def configured() -> bool:
    return bool(URL and TOKEN)


def _client() -> httpx.Client:
    return httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=TIMEOUT, trust_env=False, transport=TRANSPORT)


def _failure(method: str, kind: str, res: httpx.Response) -> RegistryError:
    log.warning("registry %s %s answered %s%s", method, kind, res.status_code,
                f", retry after {res.headers.get('Retry-After')}" if res.status_code == 429 else "")
    return RegistryError(ANSWERS.get(res.status_code, FAILED))


def _call(method: str, path: str, ok: tuple[int, ...], **kwargs) -> httpx.Response:
    kind = path.split("/")[1]
    try:
        with _client() as client:
            res = client.request(method, path, **kwargs)
    except httpx.InvalidURL:
        log.warning("registry %s %s: the address is not valid", method, kind)
        raise RegistryError(BAD_URL) from None
    except httpx.HTTPError as e:
        # the exception's text can carry the address; only its kind is logged
        log.warning("registry %s %s failed: %s", method, kind, type(e).__name__)
        raise RegistryError(UNREACHABLE) from None
    except OSError as e:
        log.warning("registry %s %s: the bundle cannot be read: %s", method, kind, type(e).__name__)
        raise RegistryError(BAD_FILE) from None
    if res.status_code not in ok:
        raise _failure(method, kind, res)
    return res


def _json(res: httpx.Response):
    try:
        return res.json()
    except ValueError:
        raise RegistryError(UNREADABLE) from None


def _chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            yield chunk


def push(version_hash: str, path: Path) -> str:
    """Store the bundle at `path` in the registry, then ask for a link to it; the link's address."""
    try:
        size = path.stat().st_size
    except OSError:
        raise RegistryError(BAD_FILE) from None
    _call("PUT", f"/bundles/{version_hash}", (200, 201), content=_chunks(path), timeout=UPLOAD_TIMEOUT,
          headers={"Content-Type": "application/zip", "Content-Length": str(size)})
    link = _json(_call("POST", "/links", (201,), json={"hash": version_hash}))
    if not (isinstance(link, dict) and isinstance(link.get("url"), str)):
        raise RegistryError(UNREADABLE)
    return link["url"]


def links() -> list[dict]:
    found = _json(_call("GET", "/links", (200,)))
    if not (isinstance(found, list) and all(isinstance(link, dict) for link in found)):
        raise RegistryError(UNREADABLE)
    return found


def share(version_hash: str, path: Path) -> str:
    """The address of the version's live link, made (and the bundle pushed) only when it has none."""
    for link in links():
        if link.get("hash") == version_hash and not link.get("revoked") and isinstance(link.get("url"), str):
            return link["url"]
    return push(version_hash, path)


def revoke(link_id: str) -> None:
    """A link the registry no longer knows is as good as revoked."""
    _call("DELETE", f"/links/{link_id}", (204, 404))
