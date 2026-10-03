"""Bridge to the speech worker in speech/, which runs in its own environment and is installed by `make speech`."""
import asyncio
import hashlib
import json
import os
from pathlib import Path

from . import db

PROJECT = db.ROOT / "speech"
AUDIO = db.DB_PATH.parent / "audio"
IDLE_SECONDS = 600
REQUEST_TIMEOUT = 300
HINT = "Speech is off. Run `make speech` once to install the local voices and the recogniser (about 7 GB)."


def available() -> bool:
    return (PROJECT / ".venv").exists() and (PROJECT / "models").exists()


class Worker:
    def __init__(self):
        self.proc: asyncio.subprocess.Process | None = None
        self.log = None
        self.lock = asyncio.Lock()
        self.idle: asyncio.TimerHandle | None = None

    async def request(self, payload: dict) -> dict:
        if not available():
            raise RuntimeError(HINT)
        async with self.lock:
            if self.proc is None or self.proc.returncode is not None:
                await self._start()
            self.proc.stdin.write((json.dumps(payload) + "\n").encode())
            await self.proc.stdin.drain()
            try:
                line = await asyncio.wait_for(self.proc.stdout.readline(), REQUEST_TIMEOUT)
            except TimeoutError:
                self.stop()
                raise RuntimeError(f"the speech worker did not answer within {REQUEST_TIMEOUT} s and was stopped") from None
            self._touch()
        if not line:
            raise RuntimeError("the speech worker stopped; see data/speech.log")
        res = json.loads(line)
        if not res.get("ok"):
            raise RuntimeError(res.get("error", "speech worker error"))
        return res

    async def _start(self) -> None:
        # Offline: models were fetched by `make speech`; nothing is downloaded while learning.
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"} | {"HF_HUB_OFFLINE": "1"}
        AUDIO.mkdir(parents=True, exist_ok=True)
        self.log = open(AUDIO.parent / "speech.log", "ab")
        self.proc = await asyncio.create_subprocess_exec(
            "uv", "run", "--no-sync", "--project", str(PROJECT), "python", str(PROJECT / "worker.py"),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=self.log,
        )

    def _touch(self) -> None:
        if self.idle:
            self.idle.cancel()
        self.idle = asyncio.get_running_loop().call_later(IDLE_SECONDS, self.stop)

    def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
        if self.log:
            self.log.close()
            self.log = None


worker = Worker()


def tts_path(text: str, lang: str) -> Path:
    return AUDIO / "tts" / f"{hashlib.sha1(f'{lang}\n{text}'.encode()).hexdigest()}.wav"


async def tts(text: str, lang: str) -> Path:
    path = tts_path(text, lang)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        await worker.request({"op": "tts", "text": text, "lang": lang, "out": str(path)})
    return path


async def stt(path: Path, lang: str | None) -> dict:
    res = await worker.request({"op": "stt", "path": str(path), "lang": lang})
    return {k: res[k] for k in ("text", "language", "words")}
