"""CrewAI BaseTool contract smoke tests (no LLM calls)."""

from __future__ import annotations

import pytest
from crewai import Agent
from pydantic import BaseModel, ValidationError

from crewai_aproxpay.client import AproxPayClient
from crewai_aproxpay.tools import (
    AproxPayCloseSessionTool,
    AproxPayCreateSessionTool,
    AproxPayExtendSessionTool,
    AproxPayListCountriesTool,
    AproxPayProxyGetTool,
    create_aproxpay_tools,
)
from tests.conftest import FakeProxy

TOOL_CLASSES = [
    AproxPayProxyGetTool,
    AproxPayListCountriesTool,
    AproxPayCreateSessionTool,
    AproxPayExtendSessionTool,
    AproxPayCloseSessionTool,
]


@pytest.fixture
def fake_client() -> AproxPayClient:
    fake = FakeProxy(lambda *a: (200, {}, "{}"))
    return AproxPayClient(base_url=fake.base_url, transport=fake)


@pytest.mark.parametrize("cls", TOOL_CLASSES)
def test_tool_has_name_description_schema(cls: type, fake_client: AproxPayClient) -> None:
    tool = cls(client=fake_client)
    assert isinstance(tool.name, str) and tool.name
    assert isinstance(tool.description, str) and tool.description
    assert issubclass(tool.args_schema, BaseModel)


def test_proxy_get_args_schema_rejects_missing_url(fake_client: AproxPayClient) -> None:
    tool = AproxPayProxyGetTool(client=fake_client)
    with pytest.raises(ValidationError):
        tool.args_schema.model_validate({})


def test_tools_attach_to_agent_without_llm_run(fake_client: AproxPayClient) -> None:
    tools = create_aproxpay_tools(client=fake_client)
    agent = Agent(
        role="Researcher",
        goal="Fetch a public IP via residential proxy",
        backstory="Uses AproxPay for geo-aware fetches.",
        tools=tools,
        allow_delegation=False,
        verbose=False,
    )
    assert len(agent.tools) == 5
    assert {t.name for t in agent.tools} == {
        "aproxpay_proxy_get",
        "aproxpay_list_countries",
        "aproxpay_create_session",
        "aproxpay_extend_session",
        "aproxpay_close_session",
    }
