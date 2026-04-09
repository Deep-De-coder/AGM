"""Configuration from environment variables."""

import os


def get_api_base_url() -> str:
    """Base URL for the AgentMemory FastAPI backend (no trailing slash)."""
    raw = os.environ.get("AGENT_MEMORY_API_URL", "http://localhost:8000").strip()
    return raw.rstrip("/")


def get_api_prefix() -> str:
    """REST API path prefix if the app is mounted under a subpath (e.g. /api/v1). Empty = /agents, /memories at root."""
    raw = os.environ.get("AGENT_MEMORY_API_PREFIX", "").strip()
    if not raw:
        return ""
    if not raw.startswith("/"):
        raw = "/" + raw
    return raw.rstrip("/")
