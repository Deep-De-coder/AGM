import type { ViolationSeverity } from "./lib/severity";

export type { ViolationSeverity };

export const API_BASE =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (init?.body != null && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${text}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export type DangerSignals = {
  anergy_ratio: number;
  source_diversity_index: number;
  reasoning_coherence: number;
  anergy_threshold_breached: boolean;
  diversity_threshold_breached: boolean;
  coherence_threshold_breached: boolean;
};

export type DashboardSummary = {
  total_memories: number;
  flagged_count: number;
  average_trust_score: number;
  active_agents_count: number;
  memories_by_source_type: Record<string, number>;
  danger_signals: DangerSignals;
  dca?: {
    last_scan_at: string | null;
    agents_in_danger: number;
    agents_semi_mature: number;
    agents_safe: number;
  } | null;
  quorum_health?: {
    full_quorum_agents: number;
    partial_quorum_agents: number;
    failed_quorum_agents: number;
  } | null;
  integrity?: { verified: number; total_with_hash: number } | null;
};

export type TrustHistoryPoint = {
  timestamp: string;
  average_trust_score: number;
  total_memories?: number;
};

export type MemoryListItem = {
  id: string;
  content: string;
  agent_id: string;
  agent_name: string | null;
  source_type: string;
  trust_score: number;
  is_flagged: boolean;
  flag_reason: string | null;
  memory_state?: string;
  reality_score?: number | null;
  created_at: string;
};

export type MemoryListResponse = {
  items: MemoryListItem[];
  total: number;
};

export type ProvenanceEvent = {
  id: string;
  event_type: string;
  performed_by_agent_id: string | null;
  event_metadata: Record<string, unknown>;
  timestamp: string;
};

export type MemoryDetail = MemoryListItem & {
  provenance: ProvenanceEvent[];
  reconsolidation?: {
    is_locked: boolean;
    has_snapshot: boolean;
    snapshot_age_seconds: number | null;
    lock_age_seconds: number | null;
  } | null;
  integrity?: { valid: boolean; violation_detected_at?: string } | null;
  causal?: Record<string, unknown> | null;
  content_hash?: string | null;
  content_hash_valid?: boolean | null;
};

export type AgentRegistryRow = {
  id: string;
  name: string;
  created_at: string;
  memory_count: number;
  avg_trust_score: number;
  flagged_memory_count: number;
};

export type AgentListResponse = {
  items: AgentRegistryRow[];
  total: number;
  limit: number;
  offset: number;
};

export type GraphPayload = {
  nodes: {
    id: string;
    kind: string;
    label: string;
    data: Record<string, unknown>;
  }[];
  edges: {
    id: string;
    source: string;
    target: string;
    label: string;
    type?: string;
    data: Record<string, unknown>;
  }[];
};

export type AgentDetail = {
  id: string;
  name: string;
  created_at: string;
  metadata: Record<string, unknown>;
  behavioral_drift_score?: number;
  system_prompt_hash?: string | null;
  behavioral_hash?: string | null;
  behavioral_hash_updated_at?: string | null;
};

export type BehavioralHashResponse = {
  agent_id: string;
  behavioral_hash: string | null;
  behavioral_hash_updated_at: string | null;
  behavioral_drift_score: number;
  behavioral_vector: Record<string, unknown> | null;
  hash_age_seconds: number;
};

export type AgentQuorumResponse = {
  agent_id: string;
  session_id: string | null;
  fast_signal: number;
  medium_signal: number;
  slow_signal: number;
  composite_score: number;
  quorum_status: "FULL_QUORUM" | "PARTIAL_QUORUM" | "FAILED_QUORUM";
  memory_trust_multiplier: number;
  failing_signals: string[];
  computed_at: string;
};

export type DcaStatsResponse = {
  agent_id: string;
  danger_score: number;
  safe_score: number;
  net_context: "SAFE" | "SEMI_MATURE" | "MATURE_DANGER";
  triggered_dangers: string[];
  triggered_safes: string[];
  sampled_at: string;
};

export type Violation = {
  id: string;
  rule_name: string;
  severity: ViolationSeverity;
  description: string;
  memory_id: string;
  agent_id?: string;
  agent_name: string | null;
  detected_at: string;
  is_acknowledged: boolean;
  acknowledged_by?: string | null;
  acknowledged_at?: string | null;
};

export type ViolationListResponse = {
  items: Violation[];
  total: number;
};

export type NotificationItem = {
  id: string;
  severity: ViolationSeverity;
  title: string;
  message: string;
  memory_id: string;
  created_at: string;
  read_at?: string | null;
  /** Some APIs use `is_read` instead of `read_at`. */
  is_read?: boolean;
};

function normalizeViolationList(data: unknown): ViolationListResponse {
  if (Array.isArray(data)) {
    return { items: data as Violation[], total: data.length };
  }
  const o = data as Record<string, unknown>;
  const items = (o.items ?? o.results ?? []) as Violation[];
  const total = Number(o.total ?? o.count ?? items.length);
  return { items, total };
}

function normalizeNotifications(data: unknown): NotificationItem[] {
  if (Array.isArray(data)) return data as NotificationItem[];
  const o = data as Record<string, unknown>;
  return (o.items ?? o.notifications ?? []) as NotificationItem[];
}

function normalizeUnreadCount(data: unknown): number {
  if (typeof data === "number") return data;
  const o = data as Record<string, unknown>;
  const n = o.count ?? o.unread_count ?? o.unread ?? 0;
  return typeof n === "number" ? n : Number(n) || 0;
}

export type GetViolationsParams = {
  severity?: ViolationSeverity | "";
  agent_id?: string;
  rule_name?: string;
  unacknowledged_only?: boolean;
  limit?: number;
};

function violationsQuery(params: GetViolationsParams): string {
  const p = new URLSearchParams();
  if (params.severity) p.set("severity", params.severity);
  if (params.agent_id?.trim()) p.set("agent_id", params.agent_id.trim());
  if (params.rule_name?.trim()) p.set("rule_name", params.rule_name.trim());
  if (params.unacknowledged_only) p.set("unacknowledged_only", "true");
  if (params.limit != null) p.set("limit", String(params.limit));
  const q = p.toString();
  return q ? `?${q}` : "";
}

export const api = {
  summary: () => fetchJson<DashboardSummary>("/stats/summary"),
  trustHistory: (hours = 24) =>
    fetchJson<TrustHistoryPoint[]>(`/stats/trust-history?hours=${hours}`),
  memories: (params: URLSearchParams) =>
    fetchJson<MemoryListResponse>(`/memories?${params.toString()}`),
  memory: (id: string) => fetchJson<MemoryDetail>(`/memories/${id}`),
  memoryProvenance: (id: string) =>
    fetchJson<ProvenanceEvent[]>(`/memories/${id}/provenance`),
  flagMemory: (id: string, reason: string) =>
    fetchJson<{ memory_id: string; flagged: boolean; reason: string }>(
      `/memories/${encodeURIComponent(id)}/flag`,
      { method: "POST", body: JSON.stringify({ reason }) },
    ),
  agents: () =>
    fetchJson<AgentListResponse>("/agents?limit=500").then((r) => r.items),
  agent: (id: string) =>
    fetchJson<AgentDetail>(`/agents/${encodeURIComponent(id)}`),
  graph: () => fetchJson<GraphPayload>("/graph"),
  runTrustDecay: () =>
    fetchJson<Record<string, number>>("/admin/run-trust-decay", {
      method: "POST",
    }),

  getViolations: async (params: GetViolationsParams = {}) => {
    const raw = await fetchJson<unknown>(`/violations${violationsQuery(params)}`);
    return normalizeViolationList(raw);
  },

  getMemoryViolations: async (memory_id: string) => {
    const raw = await fetchJson<unknown>(`/violations/${encodeURIComponent(memory_id)}`);
    if (Array.isArray(raw)) return raw as Violation[];
    const o = raw as Record<string, unknown>;
    return (o.items ?? o.violations ?? []) as Violation[];
  },

  acknowledgeViolation: (violation_id: string, acknowledged_by: string) =>
    fetchJson<Violation>(`/violations/${encodeURIComponent(violation_id)}/acknowledge`, {
      method: "POST",
      body: JSON.stringify({ acknowledged_by }),
    }),

  getNotifications: async () => {
    const raw = await fetchJson<unknown>("/notifications");
    return normalizeNotifications(raw);
  },

  markNotificationRead: (id: string) =>
    fetchJson<unknown>(`/notifications/${encodeURIComponent(id)}/read`, {
      method: "POST",
    }),

  getUnreadCount: async () => {
    const raw = await fetchJson<unknown>("/notifications/unread-count");
    return normalizeUnreadCount(raw);
  },

  getStatsDca: (agentId: string, init?: RequestInit) =>
    fetchJson<DcaStatsResponse>(`/stats/dca/${encodeURIComponent(agentId)}`, init),

  getAgentQuorum: (agentId: string, init?: RequestInit) =>
    fetchJson<AgentQuorumResponse>(
      `/agents/${encodeURIComponent(agentId)}/quorum`,
      init,
    ),

  getBehavioralHash: (agentId: string, init?: RequestInit) =>
    fetchJson<BehavioralHashResponse>(
      `/agents/${encodeURIComponent(agentId)}/behavioral-hash`,
      init,
    ),

  // Back-compat aliases used by existing pages.
  statsDca: (agentId: string) => api.getStatsDca(agentId),
  agentQuorum: (agentId: string) => api.getAgentQuorum(agentId),
  behavioralHash: (agentId: string) => api.getBehavioralHash(agentId),
};
