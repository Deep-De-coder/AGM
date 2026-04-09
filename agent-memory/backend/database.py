"""Async SQLAlchemy engine and session factory."""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Declarative base for ORM models."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def log_memory_event(
    session: AsyncSession,
    *,
    memory_id: uuid.UUID,
    event_type: str,
    performed_by_agent_id: uuid.UUID | None = None,
    event_metadata: dict[str, Any] | None = None,
) -> Any:
    """Append a row to memory_provenance_log (lazy import avoids cycles with models)."""
    from backend.models import MemoryProvenanceLog, utcnow

    row = MemoryProvenanceLog(
        memory_id=memory_id,
        event_type=event_type,
        performed_by_agent_id=performed_by_agent_id,
        event_metadata=event_metadata or {},
        timestamp=utcnow(),
    )
    session.add(row)
    await session.flush()
    return row
