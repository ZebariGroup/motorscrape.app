"""Server-Sent Events line formatting."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any


def sse_pack(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"


def sse_keepalive_ping() -> str:
    """SSE comment line — ignored by EventSource, but resets idle timers on proxies and CDNs."""
    return ": ping\n\n"


async def stream_with_keepalive(
    source: AsyncIterator[str],
    *,
    interval_s: float = 20.0,
) -> AsyncIterator[str]:
    """Yield `source` chunks while emitting comment pings so long scrapes are not killed as idle."""
    it = source.__aiter__()
    pending = asyncio.create_task(it.__anext__())
    try:
        while True:
            sleep = asyncio.create_task(asyncio.sleep(interval_s))
            await asyncio.wait({pending, sleep}, return_when=asyncio.FIRST_COMPLETED)
            if pending.done():
                sleep.cancel()
                with suppress(asyncio.CancelledError):
                    await sleep
                try:
                    chunk = pending.result()
                except StopAsyncIteration:
                    break
                yield chunk
                pending = asyncio.create_task(it.__anext__())
            else:
                yield sse_keepalive_ping()
    finally:
        if not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
