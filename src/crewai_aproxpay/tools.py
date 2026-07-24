"""CrewAI BaseTool wrappers for AproxPay."""

from __future__ import annotations

import json
from typing import Any, Literal

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from crewai_aproxpay.client import (
    AproxPayClient,
    SessionCredentials,
    ToolHttpError,
)

MAX_BODY_CHARS = 100_000


def _format_error(err: ToolHttpError) -> str:
    parts = [f"Error: {err.status} {err.error}"]
    if err.hint:
        parts.append(err.hint)
    return " — ".join(parts)


def _default_client() -> AproxPayClient:
    return AproxPayClient()


class ProxyGetInput(BaseModel):
    url: str = Field(
        description="Target URL to fetch through the residential proxy (http/https)"
    )
    sticky: bool | None = Field(
        default=None,
        description=(
            "Reuse the same exit IP for this wallet (implicit sticky session). "
            "Default true."
        ),
    )
    sticky_duration: Literal[30, 60] | None = Field(
        default=None,
        description=(
            "Sticky session TTL in minutes (30 or 60). Default 30. "
            "Only applies when sticky is true."
        ),
    )
    region: str | None = Field(
        default=None,
        description=(
            "Optional ISO 3166-1 alpha-2 exit country (e.g. us, de). "
            "Pins exit country at no surcharge. Call aproxpay_list_countries first. "
            "Omit for any-country pool."
        ),
    )


class ListCountriesInput(BaseModel):
    """No arguments — pass an empty object."""


class CreateSessionInput(BaseModel):
    tier: Literal["entry", "heavy", "gb"] | None = Field(
        default=None,
        description=(
            "Session tier: entry ($0.05, 30 min + 15MB), "
            "heavy ($0.50, 60 min + 200MB), "
            "gb ($2.50, ≤120 min + 1GB dedicated). Default entry."
        ),
    )
    region: str | None = Field(
        default=None,
        description=(
            "ISO 3166-1 alpha-2 exit country (e.g. us, de). Optional; "
            "omit for any-country pool. Call aproxpay_list_countries first. "
            "No surcharge."
        ),
    )


class ExtendSessionInput(BaseModel):
    session_id: str = Field(description="Session ID returned by aproxpay_create_session")


class CloseSessionInput(BaseModel):
    session_id: str = Field(description="Session ID returned by aproxpay_create_session")
    username: str | None = Field(
        default=None,
        description=(
            "Ephemeral gateway username (s_{sessionId}). "
            "Optional if create_session ran in this process."
        ),
    )
    password: str | None = Field(
        default=None,
        description=(
            "Ephemeral gateway password. "
            "Optional if create_session ran in this process."
        ),
    )


class _AproxPayToolBase(BaseTool):
    client: AproxPayClient = Field(default_factory=_default_client)

    model_config = {"arbitrary_types_allowed": True}


class AproxPayProxyGetTool(_AproxPayToolBase):
    name: str = "aproxpay_proxy_get"
    description: str = (
        "Fetch a URL through AproxPay residential proxy (product A). "
        "Pays ~$0.003 USDC via x402 per forwarded request (2MB cap), billed whether "
        "the origin returns 2xx or an error. Returns origin status from X-Target-Status. "
        "Sticky session is on by default. Optional `region` (ISO country from "
        "aproxpay_list_countries) pins the exit country with no surcharge."
    )
    args_schema: type[BaseModel] = ProxyGetInput

    def _run(
        self,
        url: str,
        sticky: bool | None = None,
        sticky_duration: Literal[30, 60] | None = None,
        region: str | None = None,
        **kwargs: Any,
    ) -> str:
        result = self.client.proxy_get(
            url=url,
            sticky=True if sticky is None else sticky,
            sticky_duration=sticky_duration,
            region=region,
        )
        if not result.ok:
            return _format_error(result.error)
        truncated = len(result.data.body) > MAX_BODY_CHARS
        body = (
            f"{result.data.body[:MAX_BODY_CHARS]}\n…[truncated]"
            if truncated
            else result.data.body
        )
        return json.dumps(
            {"status": result.data.status, "body": body, "truncated": truncated},
            indent=2,
        )

    async def _arun(
        self,
        url: str,
        sticky: bool | None = None,
        sticky_duration: Literal[30, 60] | None = None,
        region: str | None = None,
        **kwargs: Any,
    ) -> str:
        result = await self.client.aproxy_get(
            url=url,
            sticky=True if sticky is None else sticky,
            sticky_duration=sticky_duration,
            region=region,
        )
        if not result.ok:
            return _format_error(result.error)
        truncated = len(result.data.body) > MAX_BODY_CHARS
        body = (
            f"{result.data.body[:MAX_BODY_CHARS]}\n…[truncated]"
            if truncated
            else result.data.body
        )
        return json.dumps(
            {"status": result.data.status, "body": body, "truncated": truncated},
            indent=2,
        )


class AproxPayListCountriesTool(_AproxPayToolBase):
    name: str = "aproxpay_list_countries"
    description: str = (
        "Free discovery: return ISO 3166-1 alpha-2 exit countries accepted by "
        "aproxpay_proxy_get and aproxpay_create_session `region` (OFAC codes excluded). "
        "Call before proxy_get or create_session when you need a specific country. "
        "No payment."
    )
    args_schema: type[BaseModel] = ListCountriesInput

    def _run(self, **kwargs: Any) -> str:
        result = self.client.list_countries()
        if not result.ok:
            return _format_error(result.error)
        return json.dumps(
            {"countries": result.data.countries, "default": result.data.default},
            indent=2,
        )

    async def _arun(self, **kwargs: Any) -> str:
        result = await self.client.alist_countries()
        if not result.ok:
            return _format_error(result.error)
        return json.dumps(
            {"countries": result.data.countries, "default": result.data.default},
            indent=2,
        )


class AproxPayCreateSessionTool(_AproxPayToolBase):
    name: str = "aproxpay_create_session"
    description: str = (
        'Buy a session pass via x402 and receive ephemeral CONNECT credentials for '
        'Playwright or curl. Response includes scheme (always "https" in production), '
        "host, port, username, password, and a ready-made proxyUrl "
        "(https://user:pass@host:port). Never use plain http:// against the gateway. "
        "Tiers: entry ($0.05, 30 min + 15MB), heavy ($0.50, 60 min + 200MB), "
        "gb ($2.50, ≤120 min + 1GB dedicated). Optional region pins exit country. "
        "No automatic refund on close."
    )
    args_schema: type[BaseModel] = CreateSessionInput

    def _run(
        self,
        tier: Literal["entry", "heavy", "gb"] | None = None,
        region: str | None = None,
        **kwargs: Any,
    ) -> str:
        result = self.client.create_session(
            tier=tier or "entry",
            region=region,
        )
        if not result.ok:
            return _format_error(result.error)
        data = result.data
        payload: dict[str, Any] = {
            "scheme": data.scheme,
            "host": data.host,
            "port": data.port,
            "username": data.username,
            "password": data.password,
            "sessionId": data.session_id,
            "expiresAt": data.expires_at,
            "byteCap": data.byte_cap,
            "proxyUrl": AproxPayClient.format_proxy_url(data),
        }
        if data.region is not None:
            payload["region"] = data.region
        return json.dumps(payload, indent=2)

    async def _arun(
        self,
        tier: Literal["entry", "heavy", "gb"] | None = None,
        region: str | None = None,
        **kwargs: Any,
    ) -> str:
        result = await self.client.acreate_session(
            tier=tier or "entry",
            region=region,
        )
        if not result.ok:
            return _format_error(result.error)
        data = result.data
        payload: dict[str, Any] = {
            "scheme": data.scheme,
            "host": data.host,
            "port": data.port,
            "username": data.username,
            "password": data.password,
            "sessionId": data.session_id,
            "expiresAt": data.expires_at,
            "byteCap": data.byte_cap,
            "proxyUrl": AproxPayClient.format_proxy_url(data),
        }
        if data.region is not None:
            payload["region"] = data.region
        return json.dumps(payload, indent=2)


class AproxPayExtendSessionTool(_AproxPayToolBase):
    name: str = "aproxpay_extend_session"
    description: str = (
        "Top up an existing pooled session (+30 min TTL and +50MB cap) without changing "
        "the exit IP or country. Pays ~$0.15 USDC via x402. Not available for gb "
        "(dedicated) sessions — buy a new create_session tier=gb instead. Must be called "
        "from the same buyer wallet that created the session."
    )
    args_schema: type[BaseModel] = ExtendSessionInput

    def _run(self, session_id: str, **kwargs: Any) -> str:
        result = self.client.extend_session(session_id)
        if not result.ok:
            return _format_error(result.error)
        return json.dumps(result.data, indent=2)

    async def _arun(self, session_id: str, **kwargs: Any) -> str:
        result = await self.client.aextend_session(session_id)
        if not result.ok:
            return _format_error(result.error)
        return json.dumps(result.data, indent=2)


class AproxPayCloseSessionTool(_AproxPayToolBase):
    name: str = "aproxpay_close_session"
    description: str = (
        "Close an ephemeral session early (free, Basic-auth). Invalidates gateway "
        "credentials. Does NOT revoke the upstream sub-user and does NOT refund. "
        "Username/password optional if create_session ran in this process."
    )
    args_schema: type[BaseModel] = CloseSessionInput

    def _run(
        self,
        session_id: str,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> str:
        creds = None
        if username is not None and password is not None:
            creds = SessionCredentials(username=username, password=password)
        result = self.client.close_session(session_id, creds)
        if not result.ok:
            return _format_error(result.error)
        return json.dumps(result.data, indent=2)

    async def _arun(
        self,
        session_id: str,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> str:
        creds = None
        if username is not None and password is not None:
            creds = SessionCredentials(username=username, password=password)
        result = await self.client.aclose_session(session_id, creds)
        if not result.ok:
            return _format_error(result.error)
        return json.dumps(result.data, indent=2)


def create_aproxpay_tools(
    *,
    client: AproxPayClient | None = None,
    private_key: str | None = None,
    base_url: str | None = None,
) -> list[BaseTool]:
    """Create the full set of AproxPay CrewAI tools bound to one client."""
    resolved = client or AproxPayClient(private_key=private_key, base_url=base_url)
    return [
        AproxPayProxyGetTool(client=resolved),
        AproxPayListCountriesTool(client=resolved),
        AproxPayCreateSessionTool(client=resolved),
        AproxPayExtendSessionTool(client=resolved),
        AproxPayCloseSessionTool(client=resolved),
    ]
