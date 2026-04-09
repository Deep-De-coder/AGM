"""AgentMemory MCP server (stdio transport)."""

from mcp.server.fastmcp import FastMCP

from agent_memory_mcp.client import AgentMemoryClient
from agent_memory_mcp.config import get_api_base_url, get_api_prefix
from agent_memory_mcp.tools import register_tools

mcp = FastMCP("agent-memory")


def _default_client() -> AgentMemoryClient:
    return AgentMemoryClient(base_url=get_api_base_url(), api_prefix=get_api_prefix())


register_tools(mcp, _default_client())


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
