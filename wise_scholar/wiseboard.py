"""Handwritten boards from wise-board, a separate binary under its own EULA (see LICENSE). The server only runs it as a
subprocess: one `wise-board serve --stdio` kept warm, spoken to in JSON-RPC, one message per line. Without the binary
there are no boards and everything else works as before."""
import asyncio
import functools
import itertools
import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from concurrent.futures import Future, InvalidStateError

log = logging.getLogger("wise_scholar.wiseboard")

ENV = "WISE_BOARD_BIN"
# The binary answers every render or check within its deadline, queue wait included, refusing it when it runs out.
DEADLINE_MS = 30_000
# Past this a call is given up; the process is stopped only when it answered nothing at all since the call was sent.
TIMEOUT = DEADLINE_MS / 1000 + 30
# The binary's caps: a script and a prior doc it takes, and its replies (16 MiB), with room above for one line.
MAX_SCRIPT = 64 * 1024
MAX_PRIOR = 12 * 1024 * 1024
MAX_LINE = 24 * 1024 * 1024
STOP_WAIT = 5


class BoardError(Exception):
    """A call that did not give a board; the message is for the tutor to act on."""


class Refused(BoardError):
    """wise-board refused the call; the message is its own, line by line."""


class Busy(BoardError):
    """wise-board has too many calls waiting."""


@functools.cache
def _resolve(name: str, path: str | None) -> str | None:
    found = shutil.which(name, path=path)
    if not found and name != "wise-board":
        log.warning("%s is set to %r, which is not an executable: there are no handwritten boards", ENV, name)
    return found


def binary() -> str | None:
    """The wise-board executable: WISE_BOARD_BIN when set, else `wise-board` on PATH."""
    return _resolve(os.environ.get(ENV) or "wise-board", os.environ.get("PATH"))


def available() -> bool:
    return binary() is not None


class _Server:
    """One warm `serve --stdio` process. Replies are matched to calls by id, so calls may overlap. A writer thread
    feeds stdin and a reader thread takes stdout; a reply that is not one the protocol allows stops the process."""

    def __init__(self, path: str):
        self.path = path
        try:
            self.proc = subprocess.Popen(
                [path, "serve", "--stdio", "--deadline-ms", str(DEADLINE_MS)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            )
        except OSError as e:
            raise BoardError(f"wise-board could not start: {e}") from None
        self.ids = itertools.count(1)
        self.sent = 0
        self.replies = 0
        self.pending: dict[int, Future] = {}
        self.lock = threading.Lock()
        self.outbox: queue.Queue[bytes | None] = queue.Queue()
        self.why = ""
        self.writer = threading.Thread(target=self._write, daemon=True)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.writer.start()
        self.reader.start()

    def alive(self) -> bool:
        return not self.why and self.proc.poll() is None

    def _write(self) -> None:
        while (line := self.outbox.get()) is not None:
            try:
                self.proc.stdin.write(line)
                self.proc.stdin.flush()
            except (OSError, ValueError):
                self.stop("wise-board stopped taking calls")
                return

    def _read(self) -> None:
        try:
            while line := self.proc.stdout.readline(MAX_LINE + 1):
                if len(line) > MAX_LINE:
                    raise ValueError(f"a reply over {MAX_LINE} bytes")
                self._deliver(json.loads(line))
            self.stop(f"wise-board stopped (exit code {self._exit_code()})")
        except Exception as e:  # noqa: BLE001 - any bad reply must stop the process, never the reader alone
            self.stop(f"wise-board answered out of protocol ({e})")
        finally:
            self._exit_code()
            self.proc.stdout.close()

    def _deliver(self, reply) -> None:
        if not isinstance(reply, dict):
            raise TypeError("a reply that is not an object")
        call_id = reply.get("id")
        if not isinstance(call_id, int) or not 0 < call_id <= self.sent:
            raise TypeError(f"a reply to no call: id {call_id!r}")
        with self.lock:
            self.replies += 1
            waiting = self.pending.pop(call_id, None)
        if waiting:
            _settle(waiting, result=reply)

    def _exit_code(self) -> int | None:
        try:
            return self.proc.wait(STOP_WAIT)
        except subprocess.TimeoutExpired:
            return None

    def send(self, method: str, params: dict) -> tuple[Future, int]:
        """The call's future, and the count of replies when it went out."""
        future: Future = Future()
        body = f'"method":{json.dumps(method)},"params":{json.dumps(params, separators=(",", ":"))}'
        with self.lock:
            if self.why:
                _settle(future, error=BoardError(f"{self.why}; try again"))
                return future, self.replies
            call_id = self.sent = next(self.ids)
            self.pending[call_id] = future
            replies = self.replies
        self.outbox.put(f'{{"jsonrpc":"2.0","id":{call_id},{body}}}\n'.encode())
        return future, replies

    def forget(self, future: Future) -> None:
        with self.lock:
            self.pending = {k: f for k, f in self.pending.items() if f is not future}

    def stop(self, why: str = "wise-board was stopped") -> None:
        """Fails the calls in flight with why, kills the process and lets both threads end."""
        with self.lock:
            self.why = self.why or why
            waiting, self.pending = self.pending, {}
        for future in waiting.values():
            _settle(future, error=BoardError(f"{self.why}; try again"))
        self.outbox.put(None)
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.stdin.close()
        except OSError:
            pass


def _settle(future: Future, result=None, error: Exception | None = None) -> None:
    """Completes a future its caller may have cancelled meanwhile."""
    try:
        if error:
            future.set_exception(error)
        else:
            future.set_result(result)
    except InvalidStateError:
        pass


_server: _Server | None = None
_start = threading.Lock()


def _running() -> _Server:
    """The warm process, started again when it died or the binary changed."""
    global _server
    path = binary()
    if not path:
        raise BoardError("wise-board is not installed on this server")
    with _start:
        if not _server or not _server.alive() or _server.path != path:
            if _server:
                _server.stop()
            _server = _Server(path)
        return _server


def stop() -> None:
    """Stops the warm process, at server shutdown."""
    global _server
    with _start:
        if _server:
            _server.stop()
            _server._exit_code()
        _server = None


async def call(method: str, params: dict, timeout: float = TIMEOUT) -> dict:
    """The result of one call, `{ok: true, text, ...}`. Raises Refused with the binary's text when it refused the call,
    Busy when it has too many waiting, and BoardError for anything else."""
    server = _running()
    future, replies = server.send(method, params)
    started = time.monotonic()
    try:
        reply = await asyncio.wait_for(asyncio.wrap_future(future), timeout)
    except TimeoutError:
        server.forget(future)
        if server.replies == replies:
            server.stop(f"wise-board answered nothing for {time.monotonic() - started:.0f} seconds")
        raise BoardError(f"wise-board did not answer within {timeout:.0f} seconds; try again") from None
    if isinstance(error := reply.get("error"), dict):
        if error.get("code") == -32000:
            raise Busy("wise-board is busy with other boards; call again in a moment")
        raise BoardError(f"wise-board: {error.get('message') or error}")
    result = reply.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("ok"), bool) or not isinstance(result.get("text"), str):
        raise BoardError(f"wise-board gave a reply with no result: {json.dumps(reply)[:200]}")
    if not result["ok"]:
        raise Refused(result["text"].strip() or "wise-board refused this without saying why")
    return result


async def help_text(topic: str = "") -> str:
    return (await call("help", {"topic": topic} if topic else {}))["text"]


async def render(script: str, prior: dict | None = None) -> tuple[dict, str]:
    """The ink document the script draws and the binary's notes (`ok`, or ok and its warnings); with a prior
    document the script extends it, and the prior ink stays as it was."""
    params: dict = {"script": script, "with_doc": True}
    if prior is not None:
        params["prior"] = json.dumps(prior, separators=(",", ":"))
        if len(params["prior"]) > MAX_PRIOR:
            raise BoardError(f"this board is over {MAX_PRIOR} bytes and cannot grow; start a new board with add_board")
    result = await call("render", params)
    try:
        doc = json.loads(result["doc"])
    except (KeyError, TypeError, ValueError):
        raise BoardError("wise-board drew no ink document") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("elements"), list):
        raise BoardError("wise-board drew an ink document with no elements")
    return doc, result["text"]
