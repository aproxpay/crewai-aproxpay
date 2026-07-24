"""HTTP client for the AproxPay proxy API with x402 payment support."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Generic, Literal, Protocol, TypeVar
from urllib.parse import quote

import httpx
import requests
from eth_account import Account

CLIENT_SOURCE_HEADER = "X-Client-Source"
CLIENT_SOURCE_VALUE = "crewai"
DEFAULT_BASE_URL = "https://proxy.aproxpay.com"

SessionTier = Literal["entry", "heavy", "gb"]
StickyDuration = Literal[30, 60]

T = TypeVar("T")


@dataclass(frozen=True)
class SessionCredentials:
    username: str
    password: str


@dataclass
class SessionPass:
    scheme: Literal["http", "https"]
    host: str
    port: int
    username: str
    password: str
    session_id: str
    expires_at: str
    byte_cap: int
    region: str | None = None


@dataclass(frozen=True)
class CountriesList:
    countries: list[str]
    default: str


@dataclass(frozen=True)
class ProxyGetResult:
    status: int
    body: str


@dataclass(frozen=True)
class ToolHttpError:
    status: int
    error: str
    hint: str | None = None
    body: str | None = None


@dataclass(frozen=True)
class OkResult(Generic[T]):
    data: T
    ok: Literal[True] = True


@dataclass(frozen=True)
class ErrResult:
    error: ToolHttpError
    ok: Literal[False] = False


class HttpTransport(Protocol):
    """Test seam for paid + free HTTP calls without x402."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | str | None = None,
    ) -> tuple[int, dict[str, str], str]: ...


class _HttpxTransport:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | str | None = None,
    ) -> tuple[int, dict[str, str], str]:
        resp = self._client.request(method, url, headers=headers, content=content)
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        return resp.status_code, hdrs, resp.text


class _RequestsSessionTransport:
    def __init__(self, session: requests.Session) -> None:
        self._session = session

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | str | None = None,
    ) -> tuple[int, dict[str, str], str]:
        resp = self._session.request(method, url, headers=headers, data=content)
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        return resp.status_code, hdrs, resp.text


class AproxPayClient:
    """Thin HTTP client over the AproxPay proxy API.

    Paid routes use the official x402 SDK; every request sets
    ``X-Client-Source: crewai``.
    """

    def __init__(
        self,
        *,
        private_key: str | None = None,
        base_url: str | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        env_base = os.environ.get("APROXPROXY_BASE_URL")
        self.base_url = (base_url or env_base or DEFAULT_BASE_URL).rstrip("/")
        self._session_creds: dict[str, SessionCredentials] = {}
        self._transport = transport
        self._paid_session: requests.Session | None = None
        self._plain_client: httpx.Client | None = None
        self._x402_cm: Any = None

        if transport is not None:
            return

        key = private_key or os.environ.get("APROXPROXY_PRIVATE_KEY")
        if not key:
            raise ValueError(
                "private_key is required when transport is not provided "
                "(set APROXPROXY_PRIVATE_KEY)"
            )

        from x402 import x402ClientSync
        from x402.http.clients import x402_requests
        from x402.mechanisms.evm import EthAccountSigner
        from x402.mechanisms.evm.exact.register import register_exact_evm_client

        client = x402ClientSync()
        account = Account.from_key(key)
        register_exact_evm_client(client, EthAccountSigner(account))
        self._x402_cm = x402_requests(client)
        self._paid_session = self._x402_cm.__enter__()
        self._plain_client = httpx.Client(timeout=60.0)

    def close(self) -> None:
        if self._x402_cm is not None:
            self._x402_cm.__exit__(None, None, None)
            self._x402_cm = None
            self._paid_session = None
        if self._plain_client is not None:
            self._plain_client.close()
            self._plain_client = None

    def __enter__(self) -> AproxPayClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def get_cached_credentials(self, session_id: str) -> SessionCredentials | None:
        return self._session_creds.get(session_id)

    def clear_cached_credentials(self, session_id: str) -> None:
        self._session_creds.pop(session_id, None)

    @staticmethod
    def format_proxy_url(pass_: SessionPass) -> str:
        scheme = "http" if pass_.scheme == "http" else "https"
        user = quote(pass_.username, safe="")
        password = quote(pass_.password, safe="")
        return f"{scheme}://{user}:{password}@{pass_.host}:{pass_.port}"

    def proxy_get(
        self,
        *,
        url: str,
        sticky: bool = True,
        sticky_duration: StickyDuration | None = None,
        region: str | None = None,
    ) -> OkResult[ProxyGetResult] | ErrResult:
        body: dict[str, Any] = {"url": url, "sticky": sticky}
        if sticky_duration is not None:
            body["sticky_duration"] = sticky_duration
        if region is not None:
            body["region"] = region

        status, headers, text = self._paid_request(
            "POST",
            "/v1/proxy",
            headers={"content-type": "application/json"},
            content=json.dumps(body),
        )
        if status >= 400:
            return ErrResult(error=self._to_http_error(status, text))

        target_raw = headers.get("x-target-status")
        try:
            target_status = int(target_raw) if target_raw is not None else None
        except ValueError:
            target_status = None
        if target_status is not None and 100 <= target_status <= 599:
            origin = target_status
        else:
            origin = status
        return OkResult(data=ProxyGetResult(status=origin, body=text))

    def create_session(
        self,
        *,
        tier: SessionTier = "entry",
        region: str | None = None,
    ) -> OkResult[SessionPass] | ErrResult:
        if tier == "heavy":
            path = "/v1/session/heavy"
        elif tier == "gb":
            path = "/v1/session/gb"
        else:
            path = "/v1/session"

        body: dict[str, Any] = {}
        if region is not None:
            body["region"] = region

        status, _headers, text = self._paid_request(
            "POST",
            path,
            headers={"content-type": "application/json"},
            content=json.dumps(body),
        )
        if status >= 400:
            return ErrResult(error=self._to_http_error(status, text))

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return ErrResult(
                error=ToolHttpError(
                    status=status,
                    error="invalid JSON in session response",
                    body=text[:500],
                )
            )

        session_id = parsed.get("sessionId")
        username = parsed.get("username")
        password = parsed.get("password")
        if not isinstance(session_id, str) or not isinstance(username, str) or not isinstance(
            password, str
        ):
            return ErrResult(
                error=ToolHttpError(
                    status=status,
                    error="session response missing credentials",
                    body=text[:500],
                )
            )

        scheme = parsed.get("scheme")
        if scheme not in ("http", "https"):
            scheme = "https"

        pass_ = SessionPass(
            scheme=scheme,
            host=str(parsed.get("host", "")),
            port=int(parsed.get("port", 443)),
            username=username,
            password=password,
            session_id=session_id,
            expires_at=str(parsed.get("expiresAt", "")),
            byte_cap=int(parsed.get("byteCap", 0)),
            region=parsed.get("region") if isinstance(parsed.get("region"), str) else None,
        )
        self._session_creds[session_id] = SessionCredentials(
            username=username, password=password
        )
        return OkResult(data=pass_)

    def list_countries(self) -> OkResult[CountriesList] | ErrResult:
        status, _headers, text = self._free_request("GET", "/v1/countries")
        if status >= 400:
            return ErrResult(error=self._to_http_error(status, text))
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return ErrResult(
                error=ToolHttpError(
                    status=status,
                    error="invalid JSON in countries response",
                    body=text[:500],
                )
            )
        countries = parsed.get("countries")
        if not isinstance(countries, list):
            return ErrResult(
                error=ToolHttpError(
                    status=status,
                    error="countries response missing countries array",
                    body=text[:500],
                )
            )
        default = parsed.get("default", "any")
        return OkResult(
            data=CountriesList(
                countries=[str(c) for c in countries],
                default=str(default),
            )
        )

    def extend_session(
        self, session_id: str
    ) -> OkResult[dict[str, Any]] | ErrResult:
        status, _headers, text = self._paid_request(
            "POST",
            f"/v1/session/{quote(session_id, safe='')}/extend",
            headers={"content-type": "application/json"},
            content="{}",
        )
        if status >= 400:
            return ErrResult(error=self._to_http_error(status, text))
        try:
            return OkResult(data=json.loads(text))
        except json.JSONDecodeError:
            return ErrResult(
                error=ToolHttpError(
                    status=status,
                    error="invalid JSON in extend response",
                    body=text[:500],
                )
            )

    def close_session(
        self,
        session_id: str,
        credentials: SessionCredentials | None = None,
    ) -> OkResult[dict[str, Any]] | ErrResult:
        creds = credentials or self._session_creds.get(session_id)
        if creds is None:
            return ErrResult(
                error=ToolHttpError(
                    status=400,
                    error=(
                        "missing session credentials: pass username/password or "
                        "call create_session in this process first"
                    ),
                )
            )

        token = base64.b64encode(
            f"{creds.username}:{creds.password}".encode()
        ).decode("ascii")
        status, _headers, text = self._free_request(
            "POST",
            f"/v1/session/{quote(session_id, safe='')}/close",
            headers={"authorization": f"Basic {token}"},
        )
        if status >= 400:
            return ErrResult(error=self._to_http_error(status, text))

        self._session_creds.pop(session_id, None)
        try:
            return OkResult(data=json.loads(text))
        except json.JSONDecodeError:
            return OkResult(data={"sessionId": session_id, "closed": True})

    # --- async wrappers (asyncio.to_thread over sync client) ---

    async def aproxy_get(self, **kwargs: Any) -> OkResult[ProxyGetResult] | ErrResult:
        import asyncio

        return await asyncio.to_thread(self.proxy_get, **kwargs)

    async def acreate_session(self, **kwargs: Any) -> OkResult[SessionPass] | ErrResult:
        import asyncio

        return await asyncio.to_thread(self.create_session, **kwargs)

    async def alist_countries(self) -> OkResult[CountriesList] | ErrResult:
        import asyncio

        return await asyncio.to_thread(self.list_countries)

    async def aextend_session(self, session_id: str) -> OkResult[dict[str, Any]] | ErrResult:
        import asyncio

        return await asyncio.to_thread(self.extend_session, session_id)

    async def aclose_session(
        self,
        session_id: str,
        credentials: SessionCredentials | None = None,
    ) -> OkResult[dict[str, Any]] | ErrResult:
        import asyncio

        return await asyncio.to_thread(self.close_session, session_id, credentials)

    def _paid_request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | str | None = None,
    ) -> tuple[int, dict[str, str], str]:
        hdrs = {CLIENT_SOURCE_HEADER: CLIENT_SOURCE_VALUE}
        if headers:
            hdrs.update(headers)
        url = f"{self.base_url}{path}"

        if self._transport is not None:
            return self._transport.request(method, url, headers=hdrs, content=content)

        if self._paid_session is None:
            raise RuntimeError("client is closed")
        transport = _RequestsSessionTransport(self._paid_session)
        return transport.request(method, url, headers=hdrs, content=content)

    def _free_request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | str | None = None,
    ) -> tuple[int, dict[str, str], str]:
        hdrs = {CLIENT_SOURCE_HEADER: CLIENT_SOURCE_VALUE}
        if headers:
            hdrs.update(headers)
        url = f"{self.base_url}{path}"

        if self._transport is not None:
            return self._transport.request(method, url, headers=hdrs, content=content)

        if self._plain_client is None:
            raise RuntimeError("client is closed")
        transport = _HttpxTransport(self._plain_client)
        return transport.request(method, url, headers=hdrs, content=content)

    @staticmethod
    def _to_http_error(status: int, text: str) -> ToolHttpError:
        error = f"proxy returned {status}"
        hint: str | None = None
        try:
            payload = json.loads(text)
            if isinstance(payload.get("error"), str):
                error = payload["error"]
            if isinstance(payload.get("hint"), str):
                hint = payload["hint"]
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

        if status == 413 and hint is None:
            hint = "response exceeded byte cap — try create_session for larger transfers"

        body: str | None
        if 0 < len(text) <= 500:
            body = text
        elif len(text) > 500:
            body = f"{text[:500]}…"
        else:
            body = None

        return ToolHttpError(status=status, error=error, hint=hint, body=body)
