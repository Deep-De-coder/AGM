"""Async HTTP client for the AgentMemory REST API."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx

from agent_memory_mcp.config import get_api_base_url, get_api_prefix


class AgentMemoryClientError(Exception):
    """Raised when the AgentMemory API is unreachable or returns an error."""


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class AgentMemoryClient:
    """Wraps the AgentMemory HTTP API expected by this package."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_prefix: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._root = (base_url or get_api_base_url()).rstrip("/")
        self._prefix = (api_prefix if api_prefix is not None else get_api_prefix()).rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=f"{self._root}{self._prefix}",
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    @property
    def base_url(self) -> str:
        return self._root

    async def aclose(self) -> None:
        await self._client.aclose()

    def _unreachable_message(self) -> str:
        return (
            f"Cannot reach the AgentMemory API at {self._root}. "
            "Start the FastAPI backend (for example: `uvicorn backend.main:app --host 127.0.0.1 --port 8000` "
            "from the agent-memory project root, after configuring your database), "
            "then confirm AGENT_MEMORY_API_URL matches that server. "
            f"Current AGENT_MEMORY_API_URL resolves to: {self._root}"
        )

    async def _handle_response(self, response: httpx.Response) -> Any:
        if response.status_code >= 400:
            detail: Any
            try:
                detail = response.json()
            except json.JSONDecodeError:
                detail = response.text
            raise AgentMemoryClientError(
                f"AgentMemory API error {response.status_code} at {response.request.url!r}: {detail}"
            )
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except json.JSONDecodeError as e:
            raise AgentMemoryClientError(f"Invalid JSON from AgentMemory API: {e}") from e

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        rel = path if path.startswith("/") else f"/{path}"
        try:
            r = await self._client.request(method, rel, **kwargs)
        except httpx.TimeoutException as e:
            raise AgentMemoryClientError(
                f"Request to AgentMemory API timed out ({self._root}). "
                "Ensure the backend is running and responsive."
            ) from e
        except httpx.RequestError as e:
            raise AgentMemoryClientError(self._unreachable_message()) from e
        return await self._handle_response(r)

    async def write_memory(
        self,
        *,
        content: str,
        agent_id: str,
        source_type: str,
        source_identifier: str,
        safety_context: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "content": content,
            "agent_id": agent_id,
            "source_type": source_type,
            "source_identifier": source_identifier,
            "safety_context": safety_context or {},
        }
        if session_id is not None:
            body["session_id"] = session_id
        data = await self._request("POST", "/memories", json=body)
        if not isinstance(data, dict):
            raise AgentMemoryClientError("Unexpected response shape from POST /memories")
        out = {
            "memory_id": str(data.get("memory_id", data.get("id", ""))),
            "trust_score": float(data["trust_score"]),
        }
        if "created_at" in data and data["created_at"] is not None:
            out["created_at"] = data["created_at"]
        return _json_safe(out)

    async def read_memory(self, memory_id: str) -> dict[str, Any]:
        data = await self._request("GET", f"/memories/{memory_id}")
        if not isinstance(data, dict):
            raise AgentMemoryClientError("Unexpected response shape from GET /memories/{id}")
        return _json_safe(data)

    async def query_memories(
        self,
        *,
        agent_id: str | None = None,
        source_type: str | None = None,
        min_trust_score: float = 0.0,
        flagged_only: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "min_trust_score": min_trust_score,
            "limit": limit,
            "offset": offset,
        }
        if agent_id is not None:
            params["agent_id"] = agent_id
        if source_type is not None:
            params["source_type"] = source_type
        if flagged_only is not None:
            params["flagged_only"] = flagged_only
        data = await self._request("GET", "/memories", params=params)
        if isinstance(data, list):
            return _json_safe(data)
        if isinstance(data, dict) and "items" in data:
            return _json_safe(data["items"])
        raise AgentMemoryClientError("Unexpected response shape from GET /memories (expected list or {items})")

    async def get_trust_score(self, memory_id: str) -> dict[str, Any]:
        data = await self._request("GET", f"/memories/{memory_id}/trust")
        if not isinstance(data, dict):
            raise AgentMemoryClientError("Unexpected response from GET /memories/{id}/trust")
        out = {
            "memory_id": str(data.get("memory_id", memory_id)),
            "trust_score": float(data["trust_score"]),
            "is_flagged": bool(data.get("is_flagged", False)),
            "flag_reason": data.get("flag_reason"),
        }
        return _json_safe(out)

    async def get_provenance(self, memory_id: str) -> list[dict[str, Any]]:
        data = await self._request("GET", f"/memories/{memory_id}/provenance")
        if isinstance(data, list):
            return _json_safe(data)
        if isinstance(data, dict):
            if "events" in data:
                return _json_safe(data["events"])
            if "items" in data:
                return _json_safe(data["items"])
        raise AgentMemoryClientError(
            "Unexpected response from GET /memories/{id}/provenance (expected a list or {events})"
        )

    async def flag_memory(self, memory_id: str, reason: str) -> dict[str, Any]:
        data = await self._request("POST", f"/memories/{memory_id}/flag", json={"reason": reason})
        if not isinstance(data, dict):
            raise AgentMemoryClientError("Unexpected response from POST /memories/{id}/flag")
        out = {
            "memory_id": str(data.get("memory_id", memory_id)),
            "flagged": bool(data.get("flagged", True)),
            "reason": str(data.get("reason", reason)),
        }
        return _json_safe(out)

    async def register_agent(self, name: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        body = {"name": name, "metadata": metadata or {}}
        data = await self._request("POST", "/agents", json=body)
        if not isinstance(data, dict):
            raise AgentMemoryClientError("Unexpected response from POST /agents")
        agent_id = data.get("agent_id", data.get("id"))
        if agent_id is None:
            raise AgentMemoryClientError("Agent response missing id field")
        return _json_safe({"agent_id": str(agent_id), "name": str(data["name"])})
