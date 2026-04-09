"""Pydantic v2 request/response schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --- Agents ---
class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    behavioral_drift_score: float | None = None
    system_prompt_hash: str | None = None
    behavioral_hash: str | None = None
    behavioral_hash_updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(
        validation_alias="metadata_",
        serialization_alias="metadata",
    )


# --- Memories ---
class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=1)
    agent_id: uuid.UUID
    source_type: str = Field(..., min_length=1, max_length=128)
    source_identifier: str = Field(..., min_length=1, max_length=512)
    safety_context: dict[str, Any] = Field(default_factory=dict)
    session_id: uuid.UUID | None = None


class MemoryCreateResponse(BaseModel):
    memory_id: uuid.UUID
    trust_score: float
    created_at: datetime
    dca_warning: str | None = None
    behavioral_hash: str | None = None
    behavioral_drift: float | None = None
    content_hash: str | None = None
    quorum: dict[str, Any] | None = None
    quorum_warning: str | None = None
    rules_check: str | None = None


class MemoryProvenanceEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    memory_id: uuid.UUID
    event_type: str
    performed_by_agent_id: uuid.UUID | None
    event_metadata: dict[str, Any]
    timestamp: datetime


class MemoryDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content: str
    agent_id: uuid.UUID
    agent_name: str | None = None
    source_type: str
    source_identifier: str
    safety_context: dict[str, Any]
    trust_score: float
    is_flagged: bool
    flag_reason: str | None
    session_id: uuid.UUID | None
    memory_state: str = "active"
    reality_score: float | None = None
    created_at: datetime
    updated_at: datetime
    is_deleted: bool
    provenance: list[MemoryProvenanceEvent] = Field(default_factory=list)
    reconsolidation: dict[str, Any] | None = None
    integrity: dict[str, Any] | None = None
    causal: dict[str, Any] | None = None
    content_hash: str | None = None
    content_hash_valid: bool | None = None
    trust_recomputed: bool | None = None
    live_quorum: dict[str, Any] | None = None
    quorum_warning: str | None = None


class MemoryListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content: str
    agent_id: uuid.UUID
    agent_name: str | None = None
    source_type: str
    source_identifier: str
    safety_context: dict[str, Any]
    trust_score: float
    is_flagged: bool
    flag_reason: str | None
    session_id: uuid.UUID | None
    memory_state: str = "active"
    reality_score: float | None = None
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


class MemoryListResponse(BaseModel):
    items: list[MemoryListItem]
    total: int
    limit: int
    offset: int


class TrustUpdate(BaseModel):
    trust_score: float = Field(..., ge=0.0, le=1.0)
    performed_by_agent_id: uuid.UUID | None = None
    reason: str | None = None


class MemoryFlagBody(BaseModel):
    reason: str = Field(..., min_length=1)
    performed_by_agent_id: uuid.UUID | None = None


# --- Dashboard / stats ---
class DangerSignalsBlock(BaseModel):
    anergy_ratio: float
    source_diversity_index: float
    reasoning_coherence: float
    anergy_threshold_breached: bool
    diversity_threshold_breached: bool
    coherence_threshold_breached: bool


class DashboardSummary(BaseModel):
    total_memories: int
    flagged_count: int
    average_trust_score: float
    active_agents_count: int
    memories_by_source_type: dict[str, int]
    danger_signals: DangerSignalsBlock
    dca: dict[str, Any] | None = None
    quorum_health: dict[str, Any] | None = None
    integrity: dict[str, Any] | None = None


class TrustHistoryPoint(BaseModel):
    timestamp: datetime
    average_trust_score: float
    total_memories: int = 0


class AgentRegistryRow(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    memory_count: int
    avg_trust_score: float
    flagged_memory_count: int


class AgentListResponse(BaseModel):
    items: list[AgentRegistryRow]
    total: int
    limit: int
    offset: int


class GraphNode(BaseModel):
    id: str
    kind: str
    label: str
    data: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str
    type: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class GraphPayload(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# --- Rule violations & notifications ---
class RuleViolationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    memory_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    agent_name: str | None = None
    rule_name: str
    severity: str
    description: str | None
    is_acknowledged: bool
    acknowledged_by: str | None
    acknowledged_at: datetime | None
    detected_at: datetime
    auto_flagged: bool
    metadata: dict[str, Any] = Field(
        validation_alias="metadata_", serialization_alias="metadata"
    )


class ViolationAcknowledgeBody(BaseModel):
    acknowledged_by: str = Field(..., min_length=1, max_length=255)


class UnreadCountResponse(BaseModel):
    count: int
