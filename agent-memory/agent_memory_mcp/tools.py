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
        """
        Write a new memory with full provenance tracking.

        Stores content with source attribution, safety context, and
        trust scoring. Triggers background rule checks and behavioral
        fingerprint updates. Inter-agent memories start in anergic
        state (inactive until corroborated by 3+ trusted agents).

        Args:
          agent_id: UUID of the registered agent writing this memory.
          content: The text content to store.
          source_type: Origin of this memory. One of:
            "tool_call"   — output from a tool execution (most trusted)
            "user_input"  — direct user instruction
            "inter_agent" — received from another agent (starts anergic)
            "web_fetch"   — content from web retrieval
          source_identifier: Name or ID of the specific source
            (e.g. tool name, URL, sending agent name).
          session_id: Optional UUID of the current session.
          safety_context: Dict containing:
            channel: where this memory came from
            reality_score: float 0.0-1.0
              (1.0=direct observation, 0.3=external claim)
            cognitive_operations: list of processing steps applied
            context_hash: SHA256 hash of current session state

        Returns:
          Dict with memory_id, initial trust_score, memory_state,
          content_hash, behavioral_hash, quorum status, and
          rules_check field ("pending" — checks run in background).

        Use instead of: nothing — this is the primary write tool.
        Do NOT use for reading. Use get_safe_memories for reasoning.
        """
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
        """
        Read a specific memory by ID.

        Acquires reconsolidation lock, verifies content hash,
        validates causal chain, and recomputes trust score if stale.

        Args:
          memory_id: UUID string for the memory to retrieve.

        Returns:
          Full memory object with integrity metadata,
          live_quorum status, and reconsolidation info.

        Use when: you need a specific memory by ID.
        Use get_safe_memories instead for reasoning since it
        automatically filters unsafe memories.
        """
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
        memory_state: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Search memories with filters.

        Args:
          agent_id: Filter by writing agent UUID (optional).
          source_type: Filter by memory origin (optional).
          min_trust_score: Float minimum trust threshold (optional, default 0.0).
          flagged_only: Boolean filter to return only flagged memories (optional).
          memory_state: One of active/anergic/consolidated/quarantined (optional).
          limit: Maximum number of results to return (optional, default 50).
          offset: Pagination offset (optional, default 0).

        Returns:
          Dict containing a "memories" list of memories matching filters.

        WARNING: do not query memory_state=anergic directly — this can
        trigger RULE_013 and return 403. Use get_safe_memories for
        reasoning. Use this tool only for admin/inspection workflows.
        """
        try:
            memories = await client.query_memories(
                agent_id=agent_id,
                source_type=source_type,
                min_trust_score=min_trust_score,
                flagged_only=flagged_only,
                memory_state=memory_state,
                limit=limit,
                offset=offset,
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
        """
        Get the current trust score for a specific memory.

        Args:
          memory_id: UUID string for the memory to inspect.

        Returns:
          Dict with trust_score (float), is_flagged (bool),
          flag_reason (string or null), and last_computed_at when available.

        Use when: deciding whether to act on a memory's content.
        """
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
        """
        Get the full audit trail for a memory.

        Returns every event including writes, reads, state changes,
        rule violations, trust updates, and anomaly flags.

        Args:
          memory_id: UUID string for the memory to audit.

        Returns:
          Dict with an "events" list in chronological order.
          Each event includes event_type, performed_by_agent_id,
          metadata, and timestamp when available.

        Use when: investigating suspicious memory behavior or
        building an audit report.
        """
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
        """
        Manually flag a memory as suspicious.

        Respects reconsolidation lock semantics and may return an
        error if the memory is currently locked during retrieval.

        Args:
          memory_id: UUID of the memory to flag.
          reason: Human-readable explanation of why it is suspicious.

        Returns:
          Dict describing the updated flagged status.

        Use when: you detect suspicious content that automatic
        rules did not catch.
        """
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
        system_prompt_hash: str | None = None,
    ) -> dict[str, Any]:
        """
        Register a new agent with a behavioral baseline.

        This should be called before an agent writes any memory so
        behavioral fingerprinting and trust tracking can initialize.

        Args:
          name: Human-readable agent name.
          metadata: Optional dict of agent metadata (version, purpose, etc.).
          system_prompt_hash: Optional SHA256 of the agent system prompt
            used for identity verification and drift monitoring.

        Returns:
          Dict with agent_id (UUID), name, and created_at if provided by API.

        Use when: onboarding a new agent instance. Call once at
        startup and store the returned agent_id.
        """
        try:
            return await client.register_agent(
                name,
                metadata,
                system_prompt_hash=system_prompt_hash,
            )
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e

    @mcp.tool(
        description=(
            "Check if a memory has any rule violations. Always call this before using a memory in critical reasoning."
        )
    )
    async def check_violations(memory_id: str) -> list[dict[str, Any]]:
        """
        Get all rule violations detected for a specific memory.

        Args:
          memory_id: UUID string for the memory to inspect.

        Returns:
          List of violations, each with rule_name, severity,
          description, detected_at, and is_acknowledged.

        Use when: a memory is flagged and you need to understand why.
        """
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
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Retrieve only active, verified, non-flagged memories.

        This path is pre-filtered for reasoning safety:
        memory_state=active, is_flagged=false, trust_score >= 0.6.
        It is the default retrieval method for agent reasoning.

        Args:
          agent_id: Optional UUID to restrict results to one agent.
          limit: Maximum results to return (optional, default 50).

        Returns:
          Filtered memory list intended to be safe for reasoning use.

        Use instead of: query_memories for any reasoning task.
        """
        try:
            return await client.get_safe_memories(
                agent_id=agent_id,
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
        """
        Mark a rule violation as reviewed and resolved.

        Args:
          violation_id: UUID of the violation record.
          acknowledged_by: Name or ID of the reviewer.

        Returns:
          Updated violation object with is_acknowledged=true.

        Use when: a human has reviewed a violation and confirmed
        it is safe or already handled.
        """
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
        """
        Get the last 20 system notifications.

        Includes alerts such as DCA mature-danger events, trust-cliff
        warnings, behavioral drift, danger threshold breaches, and
        integrity or reconsolidation anomalies.

        Args:
          None.

        Returns:
          List of notifications with message, severity,
          created/timestamp fields, and read status.

        Use when: monitoring system health or investigating incidents.
        """
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
        """
        Manually trigger the 13-rule check on a specific memory.

        Rules normally run in background after writes. This tool
        forces immediate re-evaluation when context has changed.

        Args:
          memory_id: UUID string for the memory to evaluate.

        Returns:
          API response containing violations detected by this run.

        Use when: you suspect a memory should trigger a rule but
        it was written before relevant context existed.
        """
        try:
            return await client.run_rules_check(memory_id)
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e

    @mcp.tool(
        description=(
            "Manually trigger the memory consolidation cycle. "
            "Promotes corroborated anergic memories to active, "
            "quarantines contradicting anergic memories, "
            "and consolidates high-trust active memories. "
            "Returns counts of each operation performed."
        )
    )
    async def consolidate_memories() -> dict[str, Any]:
        """
        Trigger the memory consolidation cycle manually.

        Normally this runs on a background schedule. The cycle can
        promote corroborated anergic memories, quarantine unsafe
        contradictions, and consolidate high-trust active memories.

        Args:
          None.

        Returns:
          Dict containing operation counts and cycle metadata.

        Use when: immediate consolidation is required instead of
        waiting for the next background interval.
        """
        try:
            return await client.post("/admin/consolidate")
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e

    @mcp.tool(
        description=(
            "Get the static reference list of all 13 detection rules with IDs, names, "
            "severities, and descriptions."
        )
    )
    async def get_rules_reference() -> dict[str, Any]:
        """
        Get the static reference list of all 13 detection rules.

        Returns rule IDs, names, severities, and descriptions.
        This is embedded in the MCP package and requires no API call.

        Args:
          None.

        Returns:
          Dict with a rules list, total count, and source marker.

        Use when: you want to understand available rules or explain
        a violation to a user.
        """
        try:
            return await client.get_rules_reference()
        except AgentMemoryClientError as e:
            raise _tool_error(e) from e
