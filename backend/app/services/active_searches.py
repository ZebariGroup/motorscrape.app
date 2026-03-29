from __future__ import annotations

import asyncio
import threading
from typing import Any

_active_search_lock = threading.Lock()
_active_searches: dict[str, asyncio.Task[Any]] = {}


def register_active_search(correlation_id: str, task: asyncio.Task[Any]) -> None:
    with _active_search_lock:
        _active_searches[correlation_id] = task


def unregister_active_search(correlation_id: str, task: asyncio.Task[Any] | None = None) -> None:
    with _active_search_lock:
        current = _active_searches.get(correlation_id)
        if current is None:
            return
        if task is not None and current is not task:
            return
        _active_searches.pop(correlation_id, None)


def cancel_active_search(correlation_id: str) -> bool:
    with _active_search_lock:
        task = _active_searches.get(correlation_id)
    if task is None or task.done():
        return False
    task.cancel("Search canceled by user.")
    return True
