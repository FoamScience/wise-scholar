import functools
import hashlib
import http.server
import io
import os
import platform
import shutil
import subprocess
import tarfile
import threading
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fetch-wise-board.sh"
VERSION = "0.1.0"
TOOLS = "sh curl tar gzip sha256sum cut tr grep awk mktemp dirname mkdir rm mv cp cat uname".split()
ARCH = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(platform.machine())
OS = {"Linux": "unknown-linux-musl", "Darwin": "apple-darwin"}.get(platform.system())

pytestmark = pytest.mark.skipif(
    not (ARCH and OS) or any(shutil.which(t) is None for t in TOOLS), reason="needs a supported host and its tools"
)
TARGET = f"{ARCH}-{OS}"
NAME = f"wise-board-{VERSION}-{TARGET}"
ARCHIVE = f"{NAME}.tar.gz"


def fake_binary(reports=f"wise-board {VERSION}"):
    return f'#!/bin/sh\n[ "$1" = --version ] && echo "{reports}"\n'.encode()


def archive(files=None, links=()):
    """A release archive: {member: bytes} files (executable when named wise-board) and (member, target) symlinks."""
    if files is None:
        files = {
            f"{NAME}/wise-board": fake_binary(),
            f"{NAME}/EULA.md": b"EULA\n",
            f"{NAME}/THIRD-PARTY-NOTICES.txt": b"notices\n",
            f"{NAME}/notices/01-wise-board.txt": b"notice\n",
        }
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for member, data in files.items():
            info = tarfile.TarInfo(member)
            info.size = len(data)
            info.mode = 0o755 if member.endswith("/wise-board") else 0o644
            tar.addfile(info, io.BytesIO(data))
        for member, target in links:
            info = tarfile.TarInfo(member)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tar.addfile(info)
    return buf.getvalue()


class Release:
    def __init__(self, tmp_path: Path):
        self.root = tmp_path / "ws"
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPT, self.root / "scripts")
        self.mirror = tmp_path / "mirror"
        self.mirror.mkdir()
        self.tools = tmp_path / "tools"
        self.tools.mkdir()
        for t in TOOLS:
            (self.tools / t).symlink_to(shutil.which(t))
        self.dest = tmp_path / "bin" / "wise-board"
        self.version(VERSION)

    def version(self, text):
        (self.root / "wise-board.version").write_text(text + "\n")

    def publish(self, data, pin=None, sums=None, star=False):
        """Serve `data` as this host's archive; pin and list its digest unless told otherwise ("" for no line)."""
        (self.mirror / ARCHIVE).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        pin = digest if pin is None else pin
        sums = digest if sums is None else sums
        other = f"{'0' * 64}  wise-board-{VERSION}-sparc-unknown-linux-musl.tar.gz\n"
        mark = " *" if star else "  "
        (self.root / "wise-board.sha256").write_text("# pins\n" + other + (f"{pin}  {ARCHIVE}\n" if pin else ""))
        (self.mirror / "SHA256SUMS").write_text(other + (f"{sums}{mark}{ARCHIVE}\n" if sums else ""))

    def fetch(self, base=None, **env):
        env = {"PATH": str(self.tools), "WISE_BOARD_BASE_URL": base or self.mirror.as_uri(), **env}
        return subprocess.run(
            [str(self.root / "scripts" / SCRIPT.name), str(self.dest)], env=env, capture_output=True, text=True
        )


@pytest.fixture
def release(tmp_path):
    return Release(tmp_path)


def refused(done, why):
    assert done.returncode != 0, done.stdout
    assert why in done.stderr, done.stderr


def test_installs_the_pinned_archive(release):
    release.publish(archive())
    done = release.fetch()
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in release.dest.iterdir()) == [
        ".installed", "EULA.md", "THIRD-PARTY-NOTICES.txt", "notices", "wise-board",
    ]
    assert subprocess.run([release.dest / "wise-board", "--version"], capture_output=True, text=True).stdout.strip() == (
        f"wise-board {VERSION}"
    )
    assert f"fetching from {release.mirror.as_uri()}" in done.stdout
    assert "provenance not verified (gh missing or unauthenticated)" in done.stdout
    assert not [p for p in release.dest.parent.iterdir() if p.name.startswith(".wise-board.")]


def test_installs_from_a_local_http_mirror(release):
    release.publish(archive(), star=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(release.mirror))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        done = release.fetch(f"http://127.0.0.1:{server.server_address[1]}/")
    finally:
        server.shutdown()
    assert done.returncode == 0, done.stderr
    assert (release.dest / "wise-board").exists()


def test_a_failed_fetch_keeps_the_installed_one(release):
    release.publish(archive())
    assert release.fetch().returncode == 0
    release.publish(archive(), pin="1" * 64)
    refused(release.fetch(), "pins")
    assert (release.dest / "wise-board").exists()


@pytest.mark.parametrize(
    "publish, why",
    [
        (dict(pin="1" * 64), "wise-board.sha256 pins " + "1" * 64),
        (dict(pin=""), "wise-board.sha256 pins no digest"),
        (dict(sums="2" * 64), "SHA256SUMS gives " + "2" * 64),
        (dict(sums=""), "SHA256SUMS has no line"),
    ],
)
def test_refuses_an_archive_off_its_digests(release, publish, why):
    release.publish(archive(), **publish)
    refused(release.fetch(), why)
    assert not release.dest.exists()


@pytest.mark.parametrize(
    "files, links, why",
    [
        ({f"{NAME}/wise-board": fake_binary()}, (), "has no EULA.md"),
        ({f"{NAME}/EULA.md": b"EULA\n", f"{NAME}/../evil": b"x"}, (), "unexpected member"),
        ({"/etc/evil": b"x"}, (), "unexpected member"),
        ({f"{NAME}/EULA.md": b"EULA\n"}, [(f"{NAME}/wise-board", "/bin/sh")], "holds links"),
        ({f"{NAME}/wise-board": fake_binary("wise-board 9.9.9"), f"{NAME}/EULA.md": b"E"}, (), "binary reports"),
    ],
)
def test_refuses_a_malformed_archive(release, files, links, why):
    release.publish(archive(files, links))
    refused(release.fetch(), why)
    assert not release.dest.exists()


def test_refuses_a_version_not_x_y_z(release):
    release.version("0.1")
    refused(release.fetch(), "not X.Y.Z")


def test_refuses_a_host_without_a_release(release):
    (release.tools / "uname").unlink()
    (release.tools / "uname").write_text("#!/bin/sh\n[ \"$1\" = -m ] && echo sparc64 || echo Plan9\n")
    (release.tools / "uname").chmod(0o755)
    release.publish(archive())
    refused(release.fetch(), "no release for Plan9 sparc64")


def test_refuses_an_unsafe_base_url(release):
    release.publish(archive())
    refused(release.fetch("http://example.com/wise-board"), "WISE_BOARD_BASE_URL must be")


def test_require_fails_without_gh(release):
    release.publish(archive())
    refused(release.fetch(WISE_BOARD_ATTEST="require"), "WISE_BOARD_ATTEST=require, but gh is missing")
    assert not release.dest.exists()
