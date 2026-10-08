import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator

log = logging.getLogger(__name__)
_subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)
_listeners: list = []


def publish(course_id: int, event: dict) -> None:
    for queue in _subscribers[course_id]:
        queue.put_nowait(event)
    for listener in _listeners:
        try:
            listener(course_id, event)
        except Exception:
            log.exception("hub listener failed")


def listen(listener) -> None:
    """Called with (course_id, event) on every publish; for parts of the server that follow every change."""
    _listeners.append(listener)


async def subscribe(course_id: int) -> AsyncIterator[dict]:
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers[course_id].add(queue)
    try:
        while True:
            yield await queue.get()
    finally:
        _subscribers[course_id].discard(queue)
