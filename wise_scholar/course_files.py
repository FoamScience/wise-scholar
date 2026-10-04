"""Reading and writing course workspace files from the server, which runs outside the sandbox."""

import os
import stat
from pathlib import Path

# A command can make a file of any size, also a sparse one that costs it nothing: the server reads only this much.
READ_LIMIT = 2_000_000


def _open(workspace: Path, path: str, write: bool) -> int | None:
    """Open a file of the workspace without following a link anywhere on the way: a command may have planted one,
    and the server reads and writes outside the sandbox."""
    parts = Path(path).parts
    if not parts or Path(path).is_absolute() or ".." in parts:
        return None
    try:
        folder = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return None
    try:
        for part in parts[:-1]:
            if write:
                try:
                    os.mkdir(part, dir_fd=folder)
                except FileExistsError:
                    pass
            deeper = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder)
            os.close(folder)
            folder = deeper
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC if write else os.O_RDONLY
        # Non-blocking: opening a named pipe a command left behind must fail, not wait for its other end.
        fd = os.open(parts[-1], flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644, dir_fd=folder)
        if stat.S_ISREG(os.fstat(fd).st_mode):
            return fd
        os.close(fd)
        return None
    except OSError:
        return None
    finally:
        os.close(folder)


def read_text(workspace: Path, path: str) -> str | None:
    """The text of a regular file in the workspace, its first READ_LIMIT bytes; None when there is none or the
    path leaves the workspace."""
    fd = _open(workspace, path, write=False)
    if fd is None:
        return None
    with os.fdopen(fd, "rb") as f:
        return f.read(READ_LIMIT).decode(errors="replace")


def write_text(workspace: Path, path: str, content: str) -> bool:
    """Write a file in the workspace, creating its folders; False when the path leaves the workspace."""
    fd = _open(workspace, path, write=True)
    if fd is None:
        return False
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return True
