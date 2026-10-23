"""服务端事件推送（SSE）：提醒、计划、私信、通知。"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any


class EventHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queues: dict[int, set[asyncio.Queue]] = {}

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, user_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        with self._lock:
            self._queues.setdefault(user_id, set()).add(queue)
        return queue

    def unsubscribe(self, user_id: int, queue: asyncio.Queue) -> None:
        with self._lock:
            bucket = self._queues.get(user_id)
            if bucket:
                bucket.discard(queue)
                if not bucket:
                    self._queues.pop(user_id, None)

    def publish(self, user_id: int, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._enqueue, user_id, event)
        else:
            self._enqueue(user_id, event)

    def _enqueue(self, user_id: int, event: dict[str, Any]) -> None:
        with self._lock:
            bucket = list(self._queues.get(user_id, ()))
        for queue in bucket:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    def online_count(self) -> int:
        with self._lock:
            return len(self._queues)


hub = EventHub()


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
