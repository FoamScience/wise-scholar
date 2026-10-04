"""Shell commands for a course run inside bubblewrap. A command sees the system's programs, the per-user toolchains
that PATH points into and its own course workspace, which is the only place it can write. It has no network, no
sockets of the machine, none of the rest of the home directory, and capped memory, tasks and time."""

import asyncio
import functools
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path

from . import db

# WISE_SCHOLAR_COMMANDS=0 serves without command execution: no workspace tools for the tutor, no Run button.
COMMANDS = os.environ.get("WISE_SCHOLAR_COMMANDS", "1") != "0"
# WISE_SCHOLAR_SANDBOX=0 runs commands directly on the machine, as the server's user.
SANDBOX = os.environ.get("WISE_SCHOLAR_SANDBOX", "1") != "0"
TIMEOUT = 30
OUTPUT_LIMIT = 20_000
MEMORY = "2G"
TASKS = 256
SCRATCH = 256 * 1024 * 1024
# ponytail: nothing caps what a command writes into its workspace or cache; give each course a filesystem quota
# (or a loop-mounted image) before the disk is shared with people who would fill it on purpose.

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
    # The same kinds of mounts _argv makes: an older bubblewrap lacks --size.
    probe = ["--proc", "/proc", "--dev", "/dev", "--size", "1048576", "--tmpfs", "/tmp", "--remount-ro", "/", "--clearenv"]
    return subprocess.run(["bwrap", "--unshare-all", *system, *probe, "true"], capture_output=True).returncode == 0


def commands() -> bool:
    """Whether this server runs commands at all: switched on, and with its sandbox in place unless that was waived."""
    return COMMANDS and (not SANDBOX or available())


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


def _argv(command: str, workspace: Path) -> list[str]:
    home = Path.home()
    # Compilers and package tools want a cache they can write; each course has its own, beside the database.
    cache = db.DB_PATH.parent.resolve() / "sandbox-cache" / workspace.name
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
        "bwrap", "--die-with-parent", "--new-session", "--unshare-all", "--clearenv", *env,
        "--proc", "/proc", "--dev", "/dev", "--size", str(SCRATCH), "--tmpfs", "/dev/shm", "--remount-ro", "/dev",
        "--size", str(SCRATCH), "--tmpfs", "/tmp",
        "--size", str(SCRATCH), "--tmpfs", str(home),
        *visible, *masked,
        "--bind", str(cache), str(home / ".cache"),
        "--bind", str(workspace), str(workspace), "--chdir", str(workspace),
        "--remount-ro", "/",
        "sh", "-c", command,
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
_slots = asyncio.Semaphore(2)


async def run(command: str, workspace: Path) -> dict:
    """Run one shell command in a course workspace. Returns its exit code, None when it was stopped at the time
    limit, and the tail of its output."""
    async with _slots:
        return await _run(command, workspace.resolve())


async def _run(command: str, workspace: Path) -> dict:
    argv = [*_scope(), *_argv(command, workspace)] if SANDBOX else ["sh", "-c", command]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=workspace,
        # systemd-run needs the session bus of the server's own environment; bubblewrap then clears it for the command.
        env=None if SANDBOX else _env(),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    tail = b""

    async def drain() -> None:
        # Only the tail is kept: a command that prints without end must not fill the server's memory.
        nonlocal tail
        while chunk := await proc.stdout.read(65536):
            tail = (tail + chunk)[-4 * OUTPUT_LIMIT :]

    try:
        async with asyncio.timeout(TIMEOUT):
            await drain()
            await proc.wait()
        text, exit_code = tail.decode(errors="replace"), proc.returncode
    except TimeoutError:
        # Inside bubblewrap this ends everything the command started; without it, a process that left the group lives on.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        text, exit_code = f"stopped: still running after {TIMEOUT} s", None
    return {"exit_code": exit_code, "output": text[-OUTPUT_LIMIT:]}
