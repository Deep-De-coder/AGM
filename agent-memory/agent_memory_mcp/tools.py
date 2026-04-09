"""Register MCP tools that delegate to :class:`~agent_memory_mcp.client.AgentMemoryClient`."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from agent_memory_mcp.client import AgentMemoryClient, AgentMemoryClientError


def _tool_error(e: AgentMemoryClientError) -> ToolError:
    return ToolError(str(e))


def register_tools(mcp: FastMCP, client: AgentMemoryClient) -> None:
    """Attach all AgentMemory tools to the given FastMCP server."""

    @mcp.tool(
        description=(
            "Write a memory record with full provenance tracking. Every write is logged with source, "
            "agent identity, and safety context."
        )
    )
    async def write_memory(
        content: str,
        agent_id: str,
        source_type: str,
        source_identifier: str,
        safety_context: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            return await client.write_memory(
                content=content,
                agent_id=agent_id,
                source_type=source_type,
                source_identifier=source_identifier,
                safety_context=safety_context,
                session_id=session_id,
            )
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e

    @mcp.tool(
        description=(
            "Read a specific memory by ID. Access is logged in the audit trail."
        )
    )
    async def read_memory(memory_id: str) -> dict[str, Any]:
        try:
            return await client.read_memory(memory_id)
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e

    @mcp.tool(
        description=(
            "Query memories with filters. Use min_trust_score to exclude low-confidence memories from agent reasoning."
        )
    )
    async def query_memories(
        agent_id: str | None = None,
        source_type: str | None = None,
        min_trust_score: float = 0.0,
        flagged_only: bool | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        try:
            memories = await client.query_memories(
                agent_id=agent_id,
                source_type=source_type,
                min_trust_score=min_trust_score,
                flagged_only=flagged_only,
                limit=limit,
            )
            return {"memories": memories}
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e

    @mcp.tool(
        description=(
            "Get the current trust score for a memory. Trust decays over time and drops when anomalies are detected."
        )
    )
    async def get_trust_score(memory_id: str) -> dict[str, Any]:
        try:
            return await client.get_trust_score(memory_id)
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e

    @mcp.tool(
        description=(
            "Get the full audit trail for a memory record. Use this to understand the chain of custody for any "
            "piece of agent knowledge."
        )
    )
    async def get_provenance(memory_id: str) -> dict[str, Any]:
        try:
            events = await client.get_provenance(memory_id)
            return {"events": events}
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e

    @mcp.tool(
        description=(
            "Manually flag a memory as suspicious or incorrect. Flagged memories get lower trust scores and are "
            "excluded from default queries."
        )
    )
    async def flag_memory(memory_id: str, reason: str) -> dict[str, Any]:
        try:
            return await client.flag_memory(memory_id, reason)
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e

    @mcp.tool(
        description=(
            "Register a new agent identity. Returns an agent_id to use in all subsequent memory operations."
        )
    )
    async def register_agent(
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return await client.register_agent(name, metadata)
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e

    @mcp.tool(
        description=(
            "Check if a memory has any rule violations. Always call this before using a memory in critical reasoning."
        )
    )
    async def check_violations(memory_id: str) -> list[dict[str, Any]]:
        try:
            return await client.check_violations(memory_id)
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e

    @mcp.tool(
        description=(
            "Get memories that are considered safe to use in reasoning — above trust threshold, not flagged, "
            "no active violations."
        )
    )
    async def get_safe_memories(
        agent_id: str | None = None,
        min_trust_score: float = 0.6,
        exclude_flagged: bool = True,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        try:
            return await client.get_safe_memories(
                agent_id=agent_id,
                min_trust_score=min_trust_score,
                exclude_flagged=exclude_flagged,
                limit=limit,
            )
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e

    @mcp.tool(
        description=(
            "Acknowledge a rule violation after reviewing it. Use this to clear resolved alerts."
        )
    )
    async def acknowledge_violation(violation_id: str, acknowledged_by: str) -> dict[str, Any]:
        try:
            return await client.acknowledge_violation(violation_id, acknowledged_by)
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e

    @mcp.tool(
        description=(
            "Get recent security and trust notifications from the memory store. Check this periodically in "
            "long-running agent workflows."
        )
    )
    async def get_notifications() -> list[dict[str, Any]]:
        try:
            raw = await client.get_notifications(limit=20)
            return [
                {
                    "severity": r.get("severity"),
                    "title": r.get("title"),
                    "message": r.get("message"),
                    "memory_id": r.get("memory_id"),
                    "timestamp": r.get("timestamp"),
                    "read": bool(r.get("read", False)),
                }
                for r in raw
            ]
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e

    @mcp.tool(
        description=(
            "Manually trigger rule checking on a specific memory. Returns all violations found."
        )
    )
    async def run_rules_check(memory_id: str) -> dict[str, Any]:
        try:
            return await client.run_rules_check(memory_id)
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e
