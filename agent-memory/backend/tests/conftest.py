"""Pytest fixtures: SQLite test DB, mock Redis, FastAPI AsyncClient."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app


def _patch_metadata_for_sqlite(base: type[DeclarativeBase]) -> None:
    """Swap PostgreSQL-only types so create_all works on SQLite."""
    try:
        from pgvector.sqlalchemy import Vector
    except ImportError:
        Vector = ()  # type: ignore[misc,assignment]

    for table in base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()
            elif Vector and isinstance(col.type, Vector):
                col.type = JSON()


class FakeRedis:
    """Minimal async Redis stub (get/set/incr/expire/delete/lpush/ltrim/smembers/sadd/lrange)."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._lists: dict[str, list[str]] = {}
        self._sets: dict[str, set[str]] = {}

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str | float, *, ex: int | None = None) -> bool:
        self._data[key] = str(value)
        return True

    async def incr(self, key: str) -> int:
        cur = int(self._data.get(key, "0"))
        cur += 1
        self._data[key] = str(cur)
        return cur

    async def expire(self, key: str, _seconds: int) -> bool:
        return key in self._data or key in self._lists

    async def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if k in self._data:
                del self._data[k]
                n += 1
            if k in self._lists:
                del self._lists[k]
                n += 1
            if k in self._sets:
                del self._sets[k]
                n += 1
        return n

    async def lpush(self, key: str, *values: str) -> int:
        lst = self._lists.setdefault(key, [])
        for v in reversed(values):
            lst.insert(0, v)
        return len(lst)

    async def ltrim(self, key: str, start: int, end: int) -> bool:
        lst = self._lists.setdefault(key, [])
        self._lists[key] = lst[start : end + 1 if end >= 0 else None]
        return True

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        lst = self._lists.get(key, [])
        if end < 0:
            end = len(lst) - 1
        return lst[start : end + 1]

    async def sadd(self, key: str, *members: str) -> int:
        s = self._sets.setdefault(key, set())
        before = len(s)
        for m in members:
            s.add(m)
        return len(s) - before

    async def smembers(self, key: str) -> set[str]:
        return set(self._sets.get(key, set()))

    async def scan_iter(self, match: str = "*") -> Any:  # noqa: ANN401
        import fnmatch

        all_keys: set[str] = set(self._data.keys()) | set(self._lists.keys()) | set(self._sets.keys())
        for k in sorted(all_keys):
            if fnmatch.fnmatch(k, match):
                yield k

    async def ttl(self, key: str) -> int:
        if key in self._data or key in self._lists or key in self._sets:
            return 30
        return -2

    async def close(self) -> None:
        self._data.clear()
        self._lists.clear()
        self._sets.clear()


@pytest_asyncio.fixture
async def sqlite_engine():
    _patch_metadata_for_sqlite(Base)
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session_factory(sqlite_engine):
    return async_sessionmaker(
        sqlite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


@pytest_asyncio.fixture
async def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest_asyncio.fixture
async def override_db(
    sqlite_engine,
    async_session_factory,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[None, None]:
    import backend.database as database_module
    import backend.redis_client as redis_module

    database_module.engine = sqlite_engine
    database_module.AsyncSessionLocal = async_session_factory

    async def _get_redis() -> FakeRedis:
        return fake_redis

    monkeypatch.setattr(redis_module, "get_redis", _get_redis)
    monkeypatch.setattr(redis_module, "_redis", None)

    for mod in (
        "backend.trust_engine",
        "backend.routers.memories",
        "backend.routers.trust",
        "backend.rules.checker",
        "backend.routers.admin",
        "backend.routers.notifications",
        "backend.routers.stats",
        "backend.routers.agents",
        "backend.lib.behavioral_hash",
        "backend.lib.content_address",
        "backend.lib.quorum_trust",
        "backend.dendritic_cell",
        "backend.lib.reconsolidation",
    ):
        try:
            monkeypatch.setattr(f"{mod}.get_redis", _get_redis)
        except AttributeError:
            pass

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with async_session_factory() as session:
            try:
                yield session
            finally:
                await session.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield None
    finally:
        app.dependency_overrides.clear()
        monkeypatch.undo()


@pytest_asyncio.fixture
async def client(override_db: None) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
