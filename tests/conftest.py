"""Shared fake HTTP transport for client tests (no network / no x402)."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

HandlerFn = Callable[
    [str, str, dict[str, str], str],
    tuple[int, dict[str, str], str],
]


class FakeProxy:
    """In-process HttpTransport that records requests and runs a handler."""

    def __init__(self, handler: HandlerFn) -> None:
        self.handler = handler
        self.captured: list[dict[str, Any]] = []
        # Present so callers can pass base_url=fake.base_url
        self.base_url = "http://fake.local"

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | str | None = None,
    ) -> tuple[int, dict[str, str], str]:
        path = urlparse(url).path
        if isinstance(content, bytes):
            body = content.decode("utf-8")
        else:
            body = content or ""
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        self.captured.append(
            {
                "method": method,
                "path": path,
                "headers": hdrs,
                "body": body,
            }
        )
        return self.handler(method, path, hdrs, body)


def basic_auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def json_response(
    payload: dict[str, Any], status: int = 200
) -> tuple[int, dict[str, str], str]:
    return (
        status,
        {"content-type": "application/json"},
        json.dumps(payload),
    )
