"""AgentMemory MCP server (stdio transport)."""

from mcp.server.fastmcp import FastMCP

from agent_memory_mcp import __version__
from agent_memory_mcp.client import AgentMemoryClient
from agent_memory_mcp.config import get_api_base_url, get_api_prefix
from agent_memory_mcp.tools import register_tools

mcp = FastMCP("agent-memory")
_TOOLS_REGISTERED = False


def _register_runtime_tools() -> None:
    global _TOOLS_REGISTERED
    if _TOOLS_REGISTERED:
        return

    client = AgentMemoryClient(base_url=get_api_base_url(), api_prefix=get_api_prefix())
    register_tools(mcp, client)

    _TOOLS_REGISTERED = True


def main() -> None:
    import argparse
    import asyncio
    import os
    import sys

    parser = argparse.ArgumentParser(
        prog="agm-memory-mcp",
        description=(
            "AGM — Agent Memory Management MCP Server\n"
            "Provenance-tagged memory infrastructure for multi-agent "
            "AI systems.\n\n"
            "Connects to a running AgentMemory API and exposes "
            "14 MCP tools for agent memory management."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use environment variable (recommended)
  export AGENT_MEMORY_API_URL=https://your-api.example.com
  agm-memory-mcp

  # Pass URL directly
  agm-memory-mcp --api-url https://your-api.example.com

  # With path prefix
  agm-memory-mcp --api-url https://your-api.example.com --api-prefix /api/v1

  # Test connectivity before starting
  agm-memory-mcp --check

  # Check version
  agm-memory-mcp --version
      """,
    )

    parser.add_argument(
        "--api-url",
        metavar="URL",
        default=None,
        help=(
            "Base URL of the AgentMemory API "
            "(default: AGENT_MEMORY_API_URL env var, "
            "fallback: http://localhost:8000)"
        ),
    )

    parser.add_argument(
        "--api-prefix",
        metavar="PREFIX",
        default=None,
        help=(
            "Optional path prefix if API is mounted under a subpath "
            "(default: AGENT_MEMORY_API_PREFIX env var, fallback: empty)"
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Test connectivity to the AgentMemory API and exit. "
            "Exits 0 if reachable, 1 if not."
        ),
    )

    args = parser.parse_args()

    # CLI args take priority over env vars
    if args.api_url:
        os.environ["AGENT_MEMORY_API_URL"] = args.api_url
    if args.api_prefix:
        os.environ["AGENT_MEMORY_API_PREFIX"] = args.api_prefix

    if args.check:
        from agent_memory_mcp.client import AgentMemoryClient

        async def _check() -> bool:
            client = AgentMemoryClient()
            try:
                result = await client.health_check()
                print("✓ Connected to AgentMemory API")
                print(f"  URL:    {client.base_url}")
                print(f"  Status: {result.get('status', 'ok')}")
                return True
            except Exception as e:
                print(f"✗ Cannot reach AgentMemory API at {client.base_url}")
                print(f"  Error: {e}")
                print("\n  Set AGENT_MEMORY_API_URL or use --api-url")
                return False
            finally:
                await client.aclose()

        ok = asyncio.run(_check())
        sys.exit(0 if ok else 1)

    # Normal MCP server startup
    _register_runtime_tools()
    mcp.run()


if __name__ == "__main__":
    main()
