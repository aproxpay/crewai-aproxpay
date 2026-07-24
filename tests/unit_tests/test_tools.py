"""Tool run tests with fake transport."""

from __future__ import annotations

import json

from crewai_aproxpay.client import AproxPayClient
from crewai_aproxpay.tools import (
    AproxPayCreateSessionTool,
    AproxPayProxyGetTool,
    create_aproxpay_tools,
)
from tests.conftest import FakeProxy, json_response


def test_proxy_get_tool_returns_json() -> None:
    def handler(method: str, path: str, headers: dict[str, str], body: str):
        assert headers.get("x-client-source") == "crewai"
        return (
            200,
            {"content-type": "text/plain", "x-target-status": "404"},
            "not found",
        )

    fake = FakeProxy(handler)
    client = AproxPayClient(base_url=fake.base_url, transport=fake)
    tool = AproxPayProxyGetTool(client=client)
    out = tool.run(url="https://example.com/missing")
    parsed = json.loads(str(out))
    assert parsed["status"] == 404
    assert parsed["body"] == "not found"
    assert parsed["truncated"] is False


def test_proxy_get_tool_surfaces_errors() -> None:
    def handler(method: str, path: str, headers: dict[str, str], body: str):
        return json_response({"error": "URL blocked"}, status=403)

    fake = FakeProxy(handler)
    client = AproxPayClient(base_url=fake.base_url, transport=fake)
    tool = AproxPayProxyGetTool(client=client)
    out = tool.run(url="https://evil.example")
    assert "Error: 403 URL blocked" in str(out)


async def test_proxy_get_tool_arun() -> None:
    def handler(method: str, path: str, headers: dict[str, str], body: str):
        assert headers.get("x-client-source") == "crewai"
        return (
            200,
            {"content-type": "text/plain", "x-target-status": "200"},
            '{"ip":"1.2.3.4"}',
        )

    fake = FakeProxy(handler)
    client = AproxPayClient(base_url=fake.base_url, transport=fake)
    tool = AproxPayProxyGetTool(client=client)
    out = await tool._arun(url="https://api.ipify.org?format=json")
    parsed = json.loads(str(out))
    assert parsed["status"] == 200
    assert "1.2.3.4" in parsed["body"]


def test_create_session_tool_includes_proxy_url() -> None:
    def handler(method: str, path: str, headers: dict[str, str], body: str):
        return json_response(
            {
                "scheme": "https",
                "host": "gw.aproxpay.com",
                "port": 443,
                "username": "s_xyz",
                "password": "pw",
                "sessionId": "xyz",
                "expiresAt": "2099-01-01T00:00:00.000Z",
                "byteCap": 15728640,
            }
        )

    fake = FakeProxy(handler)
    client = AproxPayClient(base_url=fake.base_url, transport=fake)
    tool = AproxPayCreateSessionTool(client=client)
    out = tool.run(tier="entry")
    parsed = json.loads(str(out))
    assert parsed["proxyUrl"] == "https://s_xyz:pw@gw.aproxpay.com:443"


def test_create_aproxpay_tools_returns_five() -> None:
    fake = FakeProxy(lambda *a: (200, {}, "{}"))
    client = AproxPayClient(base_url=fake.base_url, transport=fake)
    tools = create_aproxpay_tools(client=client)
    assert len(tools) == 5
    names = {t.name for t in tools}
    assert names == {
        "aproxpay_proxy_get",
        "aproxpay_list_countries",
        "aproxpay_create_session",
        "aproxpay_extend_session",
        "aproxpay_close_session",
    }
