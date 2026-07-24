"""Client integration tests against an in-process fake transport."""

from __future__ import annotations

import json

from crewai_aproxpay.client import (
    CLIENT_SOURCE_HEADER,
    CLIENT_SOURCE_VALUE,
    AproxPayClient,
)
from tests.conftest import FakeProxy, basic_auth_header, json_response


def test_source_header_is_crewai() -> None:
    assert CLIENT_SOURCE_VALUE == "crewai"
    assert CLIENT_SOURCE_HEADER == "X-Client-Source"


def test_proxy_get_sends_source_and_reads_target_status() -> None:
    def handler(method: str, path: str, headers: dict[str, str], body: str):
        assert method == "POST"
        assert path == "/v1/proxy"
        assert headers.get("x-client-source") == "crewai"
        payload = json.loads(body)
        assert payload["url"] == "https://example.com"
        assert payload["sticky"] is True
        return (
            200,
            {"content-type": "text/plain", "x-target-status": "404"},
            "missing",
        )

    fake = FakeProxy(handler)
    client = AproxPayClient(base_url=fake.base_url, transport=fake)
    result = client.proxy_get(url="https://example.com")
    assert result.ok
    assert result.data.status == 404
    assert result.data.body == "missing"


def test_proxy_get_forwards_region_and_sticky_duration() -> None:
    def handler(method: str, path: str, headers: dict[str, str], body: str):
        payload = json.loads(body)
        assert payload == {
            "url": "https://example.com",
            "sticky": True,
            "sticky_duration": 60,
            "region": "us",
        }
        return 200, {"content-type": "text/plain", "x-target-status": "200"}, "ok"

    fake = FakeProxy(handler)
    client = AproxPayClient(base_url=fake.base_url, transport=fake)
    result = client.proxy_get(
        url="https://example.com",
        region="us",
        sticky_duration=60,
    )
    assert result.ok
    assert result.data.status == 200


def test_proxy_get_413_with_hint() -> None:
    def handler(method: str, path: str, headers: dict[str, str], body: str):
        return json_response(
            {"error": "response exceeds 2MB cap", "hint": "use /v1/proxy/large"},
            status=413,
        )

    fake = FakeProxy(handler)
    client = AproxPayClient(base_url=fake.base_url, transport=fake)
    result = client.proxy_get(url="https://example.com")
    assert not result.ok
    assert result.error.status == 413
    assert result.error.error == "response exceeds 2MB cap"
    assert result.error.hint == "use /v1/proxy/large"


def test_proxy_get_403_blocklist() -> None:
    def handler(method: str, path: str, headers: dict[str, str], body: str):
        return json_response({"error": "URL blocked"}, status=403)

    fake = FakeProxy(handler)
    client = AproxPayClient(base_url=fake.base_url, transport=fake)
    result = client.proxy_get(url="https://evil.example")
    assert not result.ok
    assert result.error.status == 403
    assert result.error.error == "URL blocked"


def test_create_session_caches_creds_for_close() -> None:
    def handler(method: str, path: str, headers: dict[str, str], body: str):
        assert headers.get("x-client-source") == "crewai"
        if method == "POST" and path == "/v1/session":
            assert json.loads(body) == {"region": "us"}
            return json_response(
                {
                    "scheme": "https",
                    "host": "gw.aproxpay.com",
                    "port": 443,
                    "username": "s_abc123",
                    "password": "secret-pass",
                    "sessionId": "abc123",
                    "expiresAt": "2099-01-01T00:00:00.000Z",
                    "byteCap": 15728640,
                    "region": "us",
                }
            )
        if method == "POST" and path == "/v1/session/abc123/close":
            assert headers.get("authorization") == basic_auth_header(
                "s_abc123", "secret-pass"
            )
            return json_response({"sessionId": "abc123", "closed": True})
        return 404, {}, "missing"

    fake = FakeProxy(handler)
    client = AproxPayClient(base_url=fake.base_url, transport=fake)

    created = client.create_session(region="us")
    assert created.ok
    assert created.data.scheme == "https"
    assert created.data.region == "us"
    assert (
        AproxPayClient.format_proxy_url(created.data)
        == "https://s_abc123:secret-pass@gw.aproxpay.com:443"
    )
    assert client.get_cached_credentials("abc123") is not None

    closed = client.close_session("abc123")
    assert closed.ok
    assert closed.data["closed"] is True
    assert client.get_cached_credentials("abc123") is None


def test_list_countries() -> None:
    def handler(method: str, path: str, headers: dict[str, str], body: str):
        assert method == "GET"
        assert path == "/v1/countries"
        assert headers.get("x-client-source") == "crewai"
        return json_response({"countries": ["us", "de"], "default": "any"})

    fake = FakeProxy(handler)
    client = AproxPayClient(base_url=fake.base_url, transport=fake)
    result = client.list_countries()
    assert result.ok
    assert result.data.countries == ["us", "de"]
    assert result.data.default == "any"


def test_close_requires_credentials() -> None:
    class _Boom:
        def request(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str] | None = None,
            content: bytes | str | None = None,
        ) -> tuple[int, dict[str, str], str]:
            raise AssertionError("should not hit network")

    client = AproxPayClient(base_url="http://127.0.0.1:9", transport=_Boom())
    result = client.close_session("missing")
    assert not result.ok
    assert result.error.status == 400
    assert "missing session credentials" in result.error.error
