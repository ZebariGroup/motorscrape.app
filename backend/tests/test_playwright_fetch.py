"""Unit tests for Playwright instruction execution helpers."""

from __future__ import annotations

import json

import pytest
from app.services.playwright_fetch import _apply_js_instructions


class _FakeResponse:
    def __init__(self, url: str, status: int) -> None:
        self.url = url
        self.status = status


class _FakePage:
    def __init__(self) -> None:
        self.url = "https://dealer.example/inventory"
        self.calls: list[tuple[str, object]] = []

    async def evaluate(self, script: str, arg: object | None = None) -> None:
        self.calls.append(("evaluate", script if arg is None else (script, arg)))

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        self.calls.append(("wait", timeout_ms))

    async def wait_for_selector(self, selector: str, **kwargs: object) -> None:
        self.calls.append(("wait_for_selector", (selector, kwargs)))

    async def click(self, selector: str, **kwargs: object) -> None:
        self.calls.append(("click", (selector, kwargs)))

    async def wait_for_url(self, predicate: object, **kwargs: object) -> None:
        self.calls.append(("wait_for_url", kwargs))
        assert callable(predicate)
        assert predicate("https://dealer.example/inventory?page=2")

    async def wait_for_response(self, predicate: object, **kwargs: object) -> None:
        self.calls.append(("wait_for_response", kwargs))
        assert callable(predicate)
        assert predicate(_FakeResponse("https://dealer.example/api/inventory", 200))


@pytest.mark.asyncio
async def test_apply_js_instructions_supports_richer_step_types() -> None:
    page = _FakePage()
    instructions = json.dumps(
        [
            {"evaluate": "window.__test=1"},
            {"wait": 250},
            {"wait_for_selector": ".vehicle-card", "timeout_ms": 3200},
            {"click": "button.load-more", "timeout_ms": 1800},
            {"wait_for_url": "page=2", "timeout_ms": 1500},
            {"wait_for_response_url": "/api/inventory", "status": 200, "timeout_ms": 2100},
            {"scroll": "bottom"},
            {"scroll": {"x": 0, "y": 900}},
            {"unknown_step": True},
        ]
    )

    await _apply_js_instructions(page, instructions)

    assert ("wait", 250) in page.calls
    assert any(name == "wait_for_selector" for name, _ in page.calls)
    assert any(name == "click" for name, _ in page.calls)
    assert any(name == "wait_for_url" for name, _ in page.calls)
    assert any(name == "wait_for_response" for name, _ in page.calls)
    assert any(name == "evaluate" and payload == "window.scrollTo(0, document.body.scrollHeight)" for name, payload in page.calls)
    assert any(
        name == "evaluate" and isinstance(payload, tuple) and payload[0] == "([x, y]) => window.scrollBy(x, y)"
        for name, payload in page.calls
    )


@pytest.mark.asyncio
async def test_apply_js_instructions_ignores_invalid_payloads() -> None:
    page = _FakePage()

    await _apply_js_instructions(page, '{"not":"a list"}')
    await _apply_js_instructions(page, "not-json")

    assert page.calls == []
