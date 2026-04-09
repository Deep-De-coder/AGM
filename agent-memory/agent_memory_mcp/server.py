"""AgentMemory MCP server (stdio transport)."""

from mcp.server.fastmcp import FastMCP

from agent_memory_mcp.client import AgentMemoryClient
from agent_memory_mcp.config import get_api_base_url, get_api_prefix
from agent_memory_mcp.tools import register_tools

mcp = FastMCP("agent-memory")

# Static reference for get_rules_reference (mirrors backend.rules.engine.PREDEFINED_RULES).
_PREDEFINED_RULES_REFERENCE: list[dict[str, str]] = [
    {
        "rule_id": "RULE_001",
        "name": "RULE_001",
        "severity": "CRITICAL",
        "description": "Session write flood (>50 writes).",
    },
    {
        "rule_id": "RULE_002",
        "name": "RULE_002",
        "severity": "HIGH",
        "description": "Agent read 3+ flagged memories in session.",
    },
    {
        "rule_id": "RULE_003",
        "name": "RULE_003",
        "severity": "MEDIUM",
        "description": "Negated facts contradict other memories from same agent.",
    },
    {
        "rule_id": "RULE_004",
        "name": "RULE_004",
        "severity": "HIGH",
        "description": "5+ provenance events within 10 minutes on same memory.",
    },
    {
        "rule_id": "RULE_005",
        "name": "RULE_005",
        "severity": "MEDIUM",
        "description": "High-stakes keywords without human verification.",
    },
    {
        "rule_id": "RULE_006",
        "name": "RULE_006",
        "severity": "LOW",
        "description": "inter_agent source without session_id.",
    },
    {
        "rule_id": "RULE_007",
        "name": "RULE_007",
        "severity": "MEDIUM",
        "description": "safety_context.context_expires_at is in the past.",
    },
    {
        "rule_id": "RULE_008",
        "name": "RULE_008",
        "severity": "HIGH",
        "description": "Agent id not present in agents table.",
    },
    {
        "rule_id": "RULE_009",
        "name": "RULE_009",
        "severity": "HIGH",
        "description": "5+ near-duplicate memories in same session.",
    },
    {
        "rule_id": "RULE_010",
        "name": "RULE_010",
        "severity": "HIGH",
        "description": "Trust dropped >0.4 in one trust_updated event.",
    },
]


def _default_client() -> AgentMemoryClient:
    return AgentMemoryClient(base_url=get_api_base_url(), api_prefix=get_api_prefix())


register_tools(mcp, _default_client())


@mcp.tool(
    description=(
        "Get the list of all predefined memory safety rules with their severities and descriptions."
    )
)
async def get_rules_reference() -> list[dict[str, str]]:
    return list(_PREDEFINED_RULES_REFERENCE)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
