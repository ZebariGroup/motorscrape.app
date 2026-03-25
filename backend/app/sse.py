"""Server-Sent Events line formatting."""

from __future__ import annotations

import json
from typing import Any


def sse_pack(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"
