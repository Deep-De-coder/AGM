"""
Tests for MCP tool contracts and error behavior.
Uses respx to mock HTTP — no Docker or live API needed.

Run with:
  pip install -e ".[test]"
  pytest tests/test_mcp_tools.py -v
"""
import pytest
import respx
import httpx
from agent_memory_mcp.client import AgentMemoryClient
from agent_memory_mcp.client import AgentMemoryClientError

MOCK_API = "http://test-api.local"


@pytest.fixture
def client():
    return AgentMemoryClient(base_url=MOCK_API)


@pytest.mark.asyncio
@respx.mock
async def test_write_memory_success(client):
    respx.post(f"{MOCK_API}/memories").mock(
        return_value=httpx.Response(201, json={
            "id": "mem-123",
            "trust_score": 0.9,
            "memory_state": "active",
            "content_hash": "abc123",
            "rules_check": "pending"
        })
    )
    result = await client.write_memory(
        agent_id="agent-1",
        content="test memory content",
        source_type="tool_call",
        source_identifier="test_tool",
        safety_context={
            "reality_score": 0.9,
            "channel": "tool_output",
            "cognitive_operations": [],
            "context_hash": "ctx-hash-1"
        }
    )
    assert result["id"] == "mem-123"
    assert result["trust_score"] == 0.9
    assert result["memory_state"] == "active"


@pytest.mark.asyncio
@respx.mock
async def test_get_safe_memories_returns_list(client):
    respx.get(f"{MOCK_API}/memories/safe").mock(
        return_value=httpx.Response(200, json={
            "memories": [],
            "total": 0
        })
    )
    result = await client.get_safe_memories(agent_id="agent-1")
    assert "memories" in result


@pytest.mark.asyncio
@respx.mock
async def test_api_unreachable_raises_friendly_error(client):
    respx.get(f"{MOCK_API}/health").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    with pytest.raises(AgentMemoryClientError):
        await client.health_check()


@pytest.mark.asyncio
async def test_get_rules_reference_embedded_requires_no_api(client):
    """
    get_rules_reference must work with zero API calls.
    It is embedded in the package — no network needed.
    """
    result = await client.get_rules_reference()
    assert result["total"] == 13
    assert result["source"] == "embedded"
    rule_ids = [r["id"] for r in result["rules"]]
    assert "RULE_001" in rule_ids
    assert "RULE_013" in rule_ids
    severities = [r["severity"] for r in result["rules"]]
    assert "CRITICAL" in severities
    assert "HIGH" in severities


@pytest.mark.asyncio
@respx.mock
async def test_register_agent_returns_agent_id(client):
    respx.post(f"{MOCK_API}/agents").mock(
        return_value=httpx.Response(201, json={
            "id": "agent-uuid-123",
            "name": "TestAgent",
            "created_at": "2026-01-01T00:00:00"
        })
    )
    result = await client.register_agent(
        name="TestAgent",
        metadata={"version": "1.0"},
        system_prompt_hash="sha256-abc"
    )
    assert result["id"] == "agent-uuid-123"
    assert result["name"] == "TestAgent"


@pytest.mark.asyncio
@respx.mock
async def test_flag_memory_409_on_locked_raises_error(client):
    respx.post(f"{MOCK_API}/memories/mem-locked/flag").mock(
        return_value=httpx.Response(409, json={
            "error": "Memory locked during reconsolidation window"
        })
    )
    with pytest.raises(AgentMemoryClientError):
        await client.flag_memory("mem-locked", "test reason")


@pytest.mark.asyncio
@respx.mock
async def test_anergy_bypass_403_raises_error(client):
    """
    Querying anergic memories directly triggers RULE_013
    and returns 403. Client must raise a clear error.
    """
    respx.get(f"{MOCK_API}/memories").mock(
        return_value=httpx.Response(403, json={
            "error": "Direct anergic memory queries are not permitted."
        })
    )
    with pytest.raises(AgentMemoryClientError):
        await client.query_memories(memory_state="anergic")


@pytest.mark.asyncio
@respx.mock
async def test_health_check_success(client):
    respx.get(f"{MOCK_API}/health").mock(
        return_value=httpx.Response(200, json={
            "status": "ok",
            "version": "0.1.0"
        })
    )
    result = await client.health_check()
    assert result["status"] == "ok"


@pytest.mark.asyncio
@respx.mock
async def test_get_trust_score(client):
    respx.get(f"{MOCK_API}/memories/mem-abc/trust").mock(
        return_value=httpx.Response(200, json={
            "memory_id": "mem-abc",
            "trust_score": 0.75,
            "is_flagged": False,
            "flag_reason": None
        })
    )
    result = await client.get_trust_score("mem-abc")
    assert result["trust_score"] == 0.75
    assert result["is_flagged"] is False


@pytest.mark.asyncio
@respx.mock
async def test_write_memory_inter_agent_starts_anergic(client):
    """
    Inter-agent memories must start anergic.
    Verify the response reflects this.
    """
    respx.post(f"{MOCK_API}/memories").mock(
        return_value=httpx.Response(201, json={
            "id": "mem-456",
            "trust_score": 0.5,
            "memory_state": "anergic",
            "content_hash": "def456",
            "rules_check": "pending"
        })
    )
    result = await client.write_memory(
        agent_id="agent-2",
        content="message from another agent",
        source_type="inter_agent",
        source_identifier="agent-sender-1",
        safety_context={
            "reality_score": 0.6,
            "channel": "inter_agent",
            "cognitive_operations": [],
            "context_hash": "ctx-hash-2"
        }
    )
    assert result["memory_state"] == "anergic"
