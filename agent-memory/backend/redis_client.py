"""Async Redis client and cache helpers."""

from redis.asyncio import Redis

from backend.config import get_settings

_settings = get_settings()


def ns_key(name: str) -> str:
    """Namespace a Redis key using :attr:`Settings.redis_namespace`."""
    ns = _settings.redis_namespace or ""
    return f"{ns}{name.lstrip(':')}"
_redis: Redis | None = None


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(
            _settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None


def trust_cache_key(memory_id: str) -> str:
    return f"trust:{memory_id}"


def session_writes_cache_key(agent_id: str, session_id: str) -> str:
    return f"writes:{agent_id}:{session_id}"


def session_flagged_reads_cache_key(agent_id: str, session_id: str) -> str:
    return f"flagged_reads:{agent_id}:{session_id}"


def session_outcome_cache_key(session_id: str) -> str:
    """Redis fallback when no row in ``sessions`` table (success / failed)."""
    return f"session_outcome:{session_id}"
