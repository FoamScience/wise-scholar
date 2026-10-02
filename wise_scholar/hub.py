import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator

_subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)


def publish(course_id: int, event: dict) -> None:
    for queue in _subscribers[course_id]:
        queue.put_nowait(event)


async def subscribe(course_id: int) -> AsyncIterator[dict]:
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers[course_id].add(queue)
    try:
        while True:
            yield await queue.get()
    finally:
        _subscribers[course_id].discard(queue)
