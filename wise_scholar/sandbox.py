"""Shell commands for a course run inside bubblewrap. A command sees the system's programs, the per-user toolchains
that PATH points into and its own course workspace, which is the only place it can write. It has no network, no
sockets of the machine, none of the rest of the home directory, and capped memory, tasks and time. A command the
learner allowed reaches the internet through the server's proxy (egress.py), and still has no network of its own."""

import asyncio
import collections
import functools
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
from pathlib import Path

from . import db, egress

# WISE_SCHOLAR_COMMANDS=0 serves without command execution: no workspace tools for the tutor, no Run button.
COMMANDS = os.environ.get("WISE_SCHOLAR_COMMANDS", "1") != "0"
# WISE_SCHOLAR_SANDBOX=0 runs commands directly on the machine, as the server's user.
SANDBOX = os.environ.get("WISE_SCHOLAR_SANDBOX", "1") != "0"
TIMEOUT = 30
NETWORK_TIMEOUT = 120
OUTPUT_LIMIT = 20_000
MEMORY = "2G"
TASKS = 256
SCRATCH = 256 * 1024 * 1024
def _megabytes(name: str, default: int) -> int:
    value = os.environ.get(name, str(default))
    if not value.isdigit() or int(value) < 1:
        raise SystemExit(f"{name} must be a whole number of megabytes, at least 1; got {value!r}")
    return int(value)


# WISE_SCHOLAR_WORKSPACE_MB: what one course may hold on disk, in its workspace and again in its command cache.
QUOTA = _megabytes("WISE_SCHOLAR_WORKSPACE_MB", 2048) * 1024 * 1024
# ponytail: the limit is watched, not enforced by the filesystem. No single file can pass it (ulimit), but a command
# is stopped only at the first look that finds its course past the limit: a fast disk takes what is written in
# between, a tree of millions of files is slow to look through, and a file deleted while still open is not seen
# until the command ends. A project quota (xfs, ext4) on the workspace folder is the hard version.
WATCH = 0.5

SYSTEM = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/etc", "/opt")
# Home folders that PATH may point into but that hold credentials, shell history or the agent's own state.
PRIVATE = {".claude", ".config", ".ssh", ".gnupg", ".aws", ".opencode", ".atuin"}
# ~/.local mixes programs with application data: only its program folders are shown.
LOCAL_PARTS = ("bin", "lib", "share/uv/python", "share/uv/tools")
COMPANIONS = {".cargo": (".rustup",)}
# ponytail: a toolchain folder is shown whole, minus the credential files known to sit in one. A token kept elsewhere
# inside such a folder is readable by commands; list a toolchain's needed parts instead if that ever matters.
MASKED = (".cargo/credentials.toml", ".cargo/credentials", ".nvm/.npmrc", ".bun/.npmrc", ".julia/config")
ENV_NAMES = {
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "TERM", "TZ",
    "GOPATH", "GOROOT", "GOBIN", "GOFLAGS", "GOTOOLCHAIN", "JAVA_HOME", "VIRTUAL_ENV",
}  # fmt: skip
ENV_PREFIXES = ("LC_", "PYENV_", "PYTHON", "NVM_", "NODE_", "BUN_", "CARGO_", "RUSTUP_", "GHCUP_", "JULIA_")
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASS|CREDENTIAL|AUTH", re.IGNORECASE)


@functools.cache
def available() -> bool:
    """Whether bubblewrap is installed and this kernel lets it make its namespaces."""
    if not shutil.which("bwrap"):
        return False
    system = [arg for path in SYSTEM for arg in ("--ro-bind-try", path, path)]
    # The same kinds of mounts _args asks for: an older bubblewrap lacks --size.
    probe = ["--proc", "/proc", "--dev", "/dev", "--size", "1048576", "--tmpfs", "/tmp", "--remount-ro", "/", "--clearenv"]
    return subprocess.run(["bwrap", "--unshare-all", *system, *probe, "true"], capture_output=True).returncode == 0


def commands() -> bool:
    """Whether this server runs commands at all: switched on, and with its sandbox in place unless that was waived."""
    return COMMANDS and (not SANDBOX or available())


def networked() -> bool:
    """Whether an allowed command can be given the internet: the relay inside the sandbox needs the system's Python."""
    return SANDBOX and available() and Path("/usr/bin/python3").exists()


def capped() -> bool:
    """Whether sandboxed commands also get the memory and task limits, which need a user systemd."""
    return bool(_scope())


def _toolchains(home: Path) -> list[Path]:
    """Per-user language toolchains: the home folders PATH points into, plus WISE_SCHOLAR_SANDBOX_PATHS."""
    # Never shown, whatever PATH or the setting says: the home directory itself, and anything that holds the
    # database or the courses.
    kept = [home, db.DB_PATH.parent.resolve(), db.WORKSPACE.resolve()]
    exposes = lambda folder: any(secret.is_relative_to(folder) for secret in kept)  # noqa: E731
    found = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        path = Path(entry)
        if not entry or not path.is_dir() or not path.is_relative_to(home) or path == home:
            continue
        top = path.relative_to(home).parts[0]
        if top in PRIVATE:
            continue
        if top == ".local":
            found += [home / top / part for part in LOCAL_PARTS]
        elif top.startswith("."):
            found += [home / top, *(home / companion for companion in COMPANIONS.get(top, ()))]
        else:
            # A bin folder runs with its siblings (lib, include); alone when those would bring the app's data along.
            found.append(path if path.name != "bin" or exposes(path.parent) else path.parent)
    found += [Path(p) for p in os.environ.get("WISE_SCHOLAR_SANDBOX_PATHS", "").split(os.pathsep) if p]
    return [p for p in dict.fromkeys(found) if p.exists() and not exposes(p.resolve())]


def _cache(workspace: Path) -> Path:
    """Compilers and package tools want a cache they can write; each course has its own, beside the database."""
    return db.DB_PATH.parent.resolve() / "sandbox-cache" / workspace.name


def _open_folder(path: str) -> int | None:
    """A descriptor for listing a folder, never through a link. A folder a command made unreadable is the
    server's own too, and is made readable again."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        return os.open(path, flags)
    except PermissionError:
        try:
            handle = os.open(path, os.O_PATH | os.O_NOFOLLOW)
            try:
                if stat.S_ISDIR(os.fstat(handle).st_mode):
                    os.chmod(f"/proc/self/fd/{handle}", 0o700)
            finally:
                os.close(handle)
            return os.open(path, flags)
        except OSError:
            return None
    except OSError:
        return None


def usage(folder: Path) -> int:
    """The bytes a folder holds on disk. Links are not followed, a sparse file counts what it really takes, and
    a file with several names counts once."""
    total, seen, pending = 0, set(), [str(folder)]
    while pending:
        path = pending.pop()
        if (fd := _open_folder(path)) is None:
            continue
        try:
            with os.scandir(fd) as entries:
                for entry in entries:
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(os.path.join(path, entry.name))
                    elif info.st_nlink > 1:
                        if (info.st_dev, info.st_ino) in seen:
                            continue
                        seen.add((info.st_dev, info.st_ino))
                    total += info.st_blocks * 512
        finally:
            os.close(fd)
    return total


def _measure(folders: list[Path]) -> list[int]:
    return [usage(folder) for folder in folders]


def _past_limit(now: list[int], low: list[int]) -> bool:
    """Past the limit and above the lowest it has been during this command. A folder that starts past the limit
    may be worked in as long as it shrinks or stays: that is how it gets emptied."""
    return any(size > QUOTA and size > least for size, least in zip(now, low))


async def _overfull(folders: list[Path], before: list[int]) -> None:
    """Returns once one of the folders is past the limit and growing."""
    low = list(before)
    while True:
        await asyncio.sleep(WATCH)
        now = await asyncio.to_thread(_measure, folders)
        if _past_limit(now, low):
            return
        low = [min(pair) for pair in zip(low, now)]


def _args(workspace: Path, extra: list[str]) -> list[str]:
    """The options of bubblewrap for one command in a workspace."""
    home = Path.home()
    cache = _cache(workspace)
    cache.mkdir(parents=True, exist_ok=True)
    toolchains = _toolchains(home)
    visible = [arg for path in (*SYSTEM, *map(str, toolchains)) for arg in ("--ro-bind-try", path, path)]
    masked = []
    for path in (home / name for name in MASKED):
        if not any(path.is_relative_to(shown) for shown in toolchains):
            continue
        if path.is_dir():
            masked += ["--tmpfs", str(path)]
        elif path.exists():
            masked += ["--ro-bind", "/dev/null", str(path)]
    env = [arg for name, value in _env().items() for arg in ("--setenv", name, value)]
    return [
        "--die-with-parent", "--new-session", "--unshare-all", "--clearenv", *env,
        "--proc", "/proc", "--dev", "/dev", "--size", str(SCRATCH), "--tmpfs", "/dev/shm", "--remount-ro", "/dev",
        "--size", str(SCRATCH), "--tmpfs", "/tmp",
        "--size", str(SCRATCH), "--tmpfs", str(home),
        *visible, *masked,
        "--bind", str(cache), str(home / ".cache"),
        "--bind", str(workspace), str(workspace), "--chdir", str(workspace),
        *extra,
        "--remount-ro", "/",
    ]  # fmt: skip


@functools.cache
def _scope() -> tuple[str, ...]:
    """A systemd scope that caps memory and task count; empty where no user systemd is running."""
    argv = (
        "systemd-run", "--user", "--scope", "--quiet", "--collect",
        "-p", f"MemoryMax={MEMORY}", "-p", "MemorySwapMax=0", "-p", f"TasksMax={TASKS}",
    )  # fmt: skip
    works = shutil.which("systemd-run") and subprocess.run([*argv, "true"], capture_output=True).returncode == 0
    return argv if works else ()


def _env() -> dict[str, str]:
    return {
        k: v
        for k, v in os.environ.items()
        if (k in ENV_NAMES or k.startswith(ENV_PREFIXES)) and not SECRET_NAME.search(k)
    }


# Each command may take its full memory and scratch space, so only a few run at once; the rest wait.
# Commands with internet run for minutes and have a queue of their own.
_slots = asyncio.Semaphore(2)
_online = asyncio.Semaphore(1)
# One command per course at a time: a second one of the same course could borrow an allowed command's relay
# through a socket in their shared workspace.
_course: dict[Path, asyncio.Lock] = collections.defaultdict(asyncio.Lock)
_awaiting_internet: set[Path] = set()
RELAY = Path(__file__).with_name("egress_relay.py")


def online(workspace: Path) -> bool:
    """Whether a command the learner allowed is waiting or running in this workspace. Its files must stay as the
    learner saw them: nothing else writes there meanwhile."""
    return workspace.resolve() in _awaiting_internet


async def run(command: str, workspace: Path, network: bool = False) -> dict:
    """Run one shell command in a course workspace. Returns its exit code, None when it was stopped at the time
    limit, and the tail of its output. network: let it reach the internet; only for a command the learner allowed."""
    workspace = workspace.resolve()
    if not (network and SANDBOX):
        async with _course[workspace], _slots:
            return await _run(command, workspace, [], [], TIMEOUT)
    # The sandbox gets no network of its own. A relay inside it offers the command an HTTP proxy on its loopback
    # and passes every connection to the server's proxy socket, which dials public addresses only.
    _awaiting_internet.add(workspace)
    try:
        async with _online, _course[workspace]:
            with tempfile.TemporaryDirectory(prefix="wise-scholar-egress-") as folder:
                proxy = await egress.serve(Path(folder) / "proxy.sock")
                try:
                    extra = ["--ro-bind", folder, "/run/egress", "--ro-bind", str(RELAY), "/run/egress-relay.py"]
                    relay = ["/usr/bin/python3", "/run/egress-relay.py", "/run/egress/proxy.sock"]
                    return await _run(command, workspace, relay, extra, NETWORK_TIMEOUT)
                finally:
                    proxy.close()
    finally:
        _awaiting_internet.discard(workspace)


async def _run(command: str, workspace: Path, wrapper: list[str], extra: list[str], limit: int) -> dict:
    megabytes = QUOTA // (1024 * 1024)
    cache = _cache(workspace)
    folders = [workspace, cache] if SANDBOX else [workspace]
    # The cache is only a cache: past its limit it is emptied, here too in case the last command could not do it.
    if SANDBOX and await asyncio.to_thread(usage, cache) > QUOTA:
        await asyncio.to_thread(shutil.rmtree, cache, True)
    before = await asyncio.to_thread(_measure, folders)
    # No single file larger than the whole limit, whatever the watch below sees or misses (ulimit counts 512-byte blocks).
    command = f"ulimit -f {QUOTA // 512}\n{command}"
    argv, fds = ["sh", "-c", command], ()
    script, options = tempfile.TemporaryFile(), tempfile.TemporaryFile()
    if SANDBOX:
        # Neither the command nor bubblewrap's options are arguments of systemd-run, which expands ${VAR} and $$
        # in what it is given from the server's own environment: the command is a file inside the sandbox, the
        # options are read from a file, and only fixed words stay on the command line.
        script.write(command.encode())
        script.seek(0)
        extra = [*extra, "--ro-bind-data", str(script.fileno()), "/run/command"]
        options.write(b"\0".join(arg.encode() for arg in _args(workspace, extra)) + b"\0")
        options.seek(0)
        argv = [*_scope(), "bwrap", "--args", str(options.fileno()), *wrapper, "sh", "/run/command"]
        fds = (script.fileno(), options.fileno())
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=workspace,
            # systemd-run needs the session bus of the server's own environment; bubblewrap then clears it for the command.
            env=None if SANDBOX else _env(),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
            pass_fds=fds,
        )
    finally:
        script.close()
        options.close()
    tail = b""

    async def finish() -> None:
        # Only the tail is kept: a command that prints without end must not fill the server's memory.
        nonlocal tail
        while chunk := await proc.stdout.read(65536):
            tail = (tail + chunk)[-4 * OUTPUT_LIMIT :]
        await proc.wait()

    work, watch = asyncio.create_task(finish()), asyncio.create_task(_overfull(folders, before))
    try:
        done, _ = await asyncio.wait({work, watch}, timeout=limit, return_when=asyncio.FIRST_COMPLETED)
        text, exit_code = tail.decode(errors="replace"), None
        if work in done:
            work.result()
            exit_code = proc.returncode
        elif watch in done:
            watch.result()
            text = f"{text[-OUTPUT_LIMIT // 2 :]}\nstopped: this course holds more than {megabytes} MB on disk; delete files to go on"
        else:
            text = f"stopped: still running after {limit} s"
    finally:
        # Also when the caller is cancelled. Inside bubblewrap this ends everything the command started; without
        # it, a process that left the group lives on.
        work.cancel()
        watch.cancel()
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
        await asyncio.gather(work, watch, return_exceptions=True)
    # A command that wrote fast and ended between two looks was not stopped: it is told, and the next one that
    # adds to the course will be.
    after = await asyncio.to_thread(_measure, folders)
    if exit_code is not None and _past_limit(after, before):
        text = f"{text[-OUTPUT_LIMIT // 2 :]}\nnote: this course now holds more than {megabytes} MB on disk; delete files before running more"
    if SANDBOX and after[-1] > QUOTA:
        await asyncio.to_thread(shutil.rmtree, cache, True)
    return {"exit_code": exit_code, "output": text[-OUTPUT_LIMIT:]}
