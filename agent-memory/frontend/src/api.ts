export const API_BASE =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${text}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export type DashboardSummary = {
  total_memories: number;
  flagged_memories: number;
  avg_trust_score: number;
  active_agents: number;
};

export type TrustHistoryPoint = {
  recorded_at: string;
  avg_trust_score: number;
  total_memories: number;
  flagged_count: number;
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
};

export type AgentRegistryRow = {
  id: string;
  name: string;
  memory_count: number;
  avg_trust_score: number;
  flagged_memory_count: number;
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
    data: Record<string, unknown>;
  }[];
};

export const api = {
  summary: () => fetchJson<DashboardSummary>("/stats/summary"),
  trustHistory: (hours = 24) =>
    fetchJson<TrustHistoryPoint[]>(`/stats/trust-history?hours=${hours}`),
  memories: (params: URLSearchParams) =>
    fetchJson<MemoryListResponse>(`/memories?${params.toString()}`),
  memory: (id: string) => fetchJson<MemoryDetail>(`/memories/${id}`),
  agents: () => fetchJson<AgentRegistryRow[]>("/agents"),
  graph: () => fetchJson<GraphPayload>("/graph"),
  runTrustDecay: () =>
    fetchJson<Record<string, number>>("/admin/run-trust-decay", {
      method: "POST",
    }),
};
