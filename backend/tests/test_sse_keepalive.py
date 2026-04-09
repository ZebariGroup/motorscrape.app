"""Tests for SSE keepalive wrapping."""

import asyncio

import pytest

from app.sse import sse_keepalive_ping, stream_with_keepalive


def test_sse_keepalive_ping_format() -> None:
    assert sse_keepalive_ping().startswith("event: ping\ndata: ")


@pytest.mark.asyncio
async def test_stream_with_keepalive_inserts_pings_between_slow_chunks() -> None:
    async def slow():
        yield "event: a\ndata: {}\n\n"
        await asyncio.sleep(0.05)
        yield "event: b\ndata: {}\n\n"

    out: list[str] = []
    async for chunk in stream_with_keepalive(slow(), interval_s=0.02):
        out.append(chunk)

    assert "event: a" in "".join(out)
    assert "event: ping\ndata: " in "".join(out)
    assert "event: b" in "".join(out)


@pytest.mark.asyncio
async def test_stream_with_keepalive_passes_through_fast_streams() -> None:
    async def fast():
        yield "x"
        yield "y"

    assert [c async for c in stream_with_keepalive(fast(), interval_s=10.0)] == ["x", "y"]
