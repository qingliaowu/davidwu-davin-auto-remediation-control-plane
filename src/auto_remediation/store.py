"""In-memory store for dispatched remediation events."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any


class MemoryStore:
    """Thread-safe circular buffer of recent remediation events."""

    def __init__(self, max_events: int = 100) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._lock = asyncio.Lock()

    async def record(self, event: dict[str, Any]) -> None:
        async with self._lock:
            self._events.append(event)

    async def list(self) -> list[dict[str, Any]]:
        async with self._lock:
            return list(self._events)


store = MemoryStore()
