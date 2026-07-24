"""CrewAI tools for AproxPay residential proxy (x402)."""

from crewai_aproxpay.client import (
    CLIENT_SOURCE_HEADER,
    CLIENT_SOURCE_VALUE,
    DEFAULT_BASE_URL,
    AproxPayClient,
    CountriesList,
    ErrResult,
    OkResult,
    ProxyGetResult,
    SessionCredentials,
    SessionPass,
    ToolHttpError,
)
from crewai_aproxpay.tools import (
    MAX_BODY_CHARS,
    AproxPayCloseSessionTool,
    AproxPayCreateSessionTool,
    AproxPayExtendSessionTool,
    AproxPayListCountriesTool,
    AproxPayProxyGetTool,
    create_aproxpay_tools,
)

__all__ = [
    "CLIENT_SOURCE_HEADER",
    "CLIENT_SOURCE_VALUE",
    "DEFAULT_BASE_URL",
    "MAX_BODY_CHARS",
    "AproxPayClient",
    "AproxPayCloseSessionTool",
    "AproxPayCreateSessionTool",
    "AproxPayExtendSessionTool",
    "AproxPayListCountriesTool",
    "AproxPayProxyGetTool",
    "CountriesList",
    "ErrResult",
    "OkResult",
    "ProxyGetResult",
    "SessionCredentials",
    "SessionPass",
    "ToolHttpError",
    "create_aproxpay_tools",
]

__version__ = "0.1.0"
