# AproxPay CrewAI

CrewAI tools for [AproxPay](https://aproxpay.com) — residential proxy with
native **x402** payments (USDC on Base). No signup, no API key: a buyer wallet
signs EIP-3009 transfers per request or session pass.

```bash
pip install crewai-aproxpay
# or: uv add crewai-aproxpay
```

Requires **Python >=3.10,<3.14** (CrewAI constraint).

Every request sets `X-Client-Source: crewai` so AproxPay funnel metrics
attribute traffic correctly.

## Quickstart

```bash
export APROXPROXY_PRIVATE_KEY=0x…   # dedicated low-balance buyer wallet on Base
```

```python
from crewai import Agent, Task, Crew
from crewai_aproxpay import AproxPayProxyGetTool, create_aproxpay_tools

# Single hero tool:
agent = Agent(
    role="Researcher",
    goal="Fetch public pages via residential IP",
    backstory="Uses AproxPay for geo-aware HTTP fetches.",
    tools=[AproxPayProxyGetTool()],
    verbose=True,
)

# Or bind the full set (shared client / session credential cache):
# tools = create_aproxpay_tools()

task = Task(
    description="Fetch https://api.ipify.org?format=json and report the IP.",
    expected_output="JSON with the observed public IP",
    agent=agent,
)

Crew(agents=[agent], tasks=[task]).kickoff()
```

Direct call without an LLM (useful for smoke tests):

```python
from crewai_aproxpay import AproxPayProxyGetTool

print(AproxPayProxyGetTool().run(url="https://api.ipify.org?format=json"))
```

## Environment

| Variable | Required | Default | Notes |
|---|---|---|---|
| `APROXPROXY_PRIVATE_KEY` | yes (unless injecting a test transport) | — | `0x` + 64 hex. Use a **dedicated low-balance** buyer wallet funded with USDC on Base. Never commit or log this value. |
| `APROXPROXY_BASE_URL` | no | `https://proxy.aproxpay.com` | Override for staging/local. |

## Tools

| Tool | Pays | Purpose |
|---|---|---|
| `aproxpay_proxy_get` | ~$0.003 | Hero: fetch a URL via residential IP (2MB cap). Optional `region`, `sticky`, `sticky_duration`. |
| `aproxpay_list_countries` | free | ISO exit countries for `region`. |
| `aproxpay_create_session` | tiered | Ephemeral CONNECT credentials for Playwright / curl. |
| `aproxpay_extend_session` | ~$0.15 | +30 min / +50MB (not for `gb` tier). |
| `aproxpay_close_session` | free | Invalidate credentials (no refund). |

Product A success responses are HTTP **200** with origin status in
`X-Target-Status` — tools return that origin status, not the envelope 200.

## Session pass (Playwright)

```python
from crewai_aproxpay import AproxPayCreateSessionTool
import json

raw = AproxPayCreateSessionTool().run(tier="entry", region="us")
session = json.loads(raw)
# Always use the https proxy URL — never plain http:// against gw:443
proxy_url = session["proxyUrl"]  # https://user:pass@gw.aproxpay.com:443
```

Production gateway is TLS on **:443**. Documented fallback: same credentials on
`:8443` (`https://user:pass@gw.aproxpay.com:8443`). Plain `http://` to `:443`
hits the web front and returns 404.

## Pricing

See [aproxpay.com/pricing](https://aproxpay.com/pricing) for the live ladder.
Approximate MVP tiers:

| Product | Price | Cap |
|---|---|---|
| Per-request (`proxy_get`) | $0.003 | 2MB |
| Per-request large | $0.015 | 5MB |
| Session entry | $0.05 | 30 min + 15MB |
| Session heavy | $0.50 | 60 min + 200MB |
| Session gb | $2.50 | ≤120 min + 1GB dedicated |
| Extend | $0.15 | +30 min + 50MB |

## Security

- Keep the buyer private key on the machine that runs the agent (non-custodial).
- Do not log `APROXPROXY_PRIVATE_KEY`, `Authorization`, or payment headers.
- Close session early if you are done — there is **no automatic refund**.

## Development

```bash
uv sync --group dev
uv run ruff check src tests
uv run mypy src
uv run pytest

# Local secret + public-deny hooks (optional, mirrors CI)
pipx install pre-commit && pre-commit install
pre-commit run --all-files
```

## License

MIT © AproxPay
