import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  AgentDetail,
  AgentQuorumResponse,
  BehavioralHashResponse,
  DcaStatsResponse,
  MemoryListItem,
  ProvenanceEvent,
} from "../api";
import { Badge, Button, Card, cn } from "./ui";

type AgentDetailPanelProps = {
  agentId: string;
  agentName: string;
  onClose: () => void;
};

type TabKey = "overview" | "identity" | "quorum";

type HashTimelineEvent = {
  id: string;
  timestamp: string;
  oldHash: string | null;
  newHash: string | null;
  driftScore: number | null;
};

function ago(ts: string | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "—";
  const sec = Math.max(1, Math.floor((Date.now() - d.getTime()) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}

function driftColor(score: number): string {
  if (score < 0.2) return "bg-emerald-500";
  if (score <= 0.4) return "bg-amber-500";
  return "bg-red-500";
}

function signalColor(score: number): string {
  if (score > 0.6) return "bg-emerald-500";
  if (score >= 0.3) return "bg-amber-500";
  return "bg-red-500";
}

function dcaBadge(ctx: DcaStatsResponse["net_context"] | undefined) {
  const c = ctx ?? "SAFE";
  if (c === "SAFE") {
    return <Badge className="bg-emerald-500/20 text-emerald-300">SAFE</Badge>;
  }
  if (c === "SEMI_MATURE") {
    return <Badge className="bg-amber-500/20 text-amber-300">SEMI_MATURE</Badge>;
  }
  return (
    <Badge className="animate-pulse bg-red-600/30 text-red-200 border border-red-500/50">
      MATURE_DANGER
    </Badge>
  );
}

function quorumBadge(status: AgentQuorumResponse["quorum_status"] | undefined) {
  const s = status ?? "FULL_QUORUM";
  if (s === "FULL_QUORUM") {
    return <Badge className="bg-emerald-500/20 text-emerald-300">FULL_QUORUM</Badge>;
  }
  if (s === "PARTIAL_QUORUM") {
    return <Badge className="bg-amber-500/20 text-amber-300">PARTIAL_QUORUM</Badge>;
  }
  return <Badge className="bg-red-500/20 text-red-300">FAILED_QUORUM</Badge>;
}

function truncateHash(v: string | null | undefined, n: number): string {
  if (!v) return "—";
  return v.length > n ? `${v.slice(0, n)}...` : v;
}

function LoadingSkeleton() {
  return (
    <div className="space-y-2">
      <div className="h-3 w-2/3 animate-pulse rounded bg-zinc-800" />
      <div className="h-3 w-1/2 animate-pulse rounded bg-zinc-800" />
      <div className="h-3 w-3/4 animate-pulse rounded bg-zinc-800" />
    </div>
  );
}

export function AgentDetailPanel({
  agentId,
  agentName,
  onClose,
}: AgentDetailPanelProps) {
  const [tab, setTab] = useState<TabKey>("overview");

  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [agentStats, setAgentStats] = useState<{ memoryCount: number } | null>(null);
  const [agentLoading, setAgentLoading] = useState<boolean>(true);
  const [agentError, setAgentError] = useState<string | null>(null);

  const [dca, setDca] = useState<DcaStatsResponse | null>(null);
  const [dcaLoading, setDcaLoading] = useState<boolean>(true);
  const [dcaError, setDcaError] = useState<string | null>(null);

  const [quorum, setQuorum] = useState<AgentQuorumResponse | null>(null);
  const [quorumLoading, setQuorumLoading] = useState<boolean>(true);
  const [quorumError, setQuorumError] = useState<string | null>(null);

  const [behavioral, setBehavioral] = useState<BehavioralHashResponse | null>(null);
  const [behavioralLoading, setBehavioralLoading] = useState<boolean>(true);
  const [behavioralError, setBehavioralError] = useState<string | null>(null);

  const [hashEvents, setHashEvents] = useState<HashTimelineEvent[]>([]);
  const [historyLoading, setHistoryLoading] = useState<boolean>(true);
  const [historyError, setHistoryError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    let active = true;
    async function loadOverview(signal: AbortSignal) {
      setAgentLoading(true);
      setAgentError(null);
      try {
        const [agentRow, allAgents] = await Promise.all([
          api.agent(agentId),
          api.agents(),
        ]);
        if (!active) return;
        setAgent(agentRow);
        const stat = allAgents.find((a) => a.id === agentId);
        setAgentStats({ memoryCount: stat?.memory_count ?? 0 });
      } catch (err) {
        if (!active || signal.aborted) return;
        setAgentError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (active) setAgentLoading(false);
      }
    }
    loadOverview(ac.signal);
    return () => {
      active = false;
      ac.abort();
    };
  }, [agentId]);

  useEffect(() => {
    const ac = new AbortController();
    let active = true;
    async function loadDca(signal: AbortSignal) {
      setDcaLoading(true);
      setDcaError(null);
      try {
        const row = await api.getStatsDca(agentId, { signal });
        if (!active) return;
        setDca(row);
      } catch (err) {
        if (!active || signal.aborted) return;
        setDcaError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (active) setDcaLoading(false);
      }
    }
    loadDca(ac.signal);
    return () => {
      active = false;
      ac.abort();
    };
  }, [agentId]);

  useEffect(() => {
    let active = true;
    const controllers: AbortController[] = [];
    async function pollQuorum() {
      const ac = new AbortController();
      controllers.push(ac);
      try {
        const row = await api.getAgentQuorum(agentId, { signal: ac.signal });
        if (!active) return;
        setQuorum(row);
        setQuorumError(null);
      } catch (err) {
        if (!active || ac.signal.aborted) return;
        setQuorumError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (active) setQuorumLoading(false);
      }
    }
    setQuorumLoading(true);
    pollQuorum();
    const timer = window.setInterval(pollQuorum, 30_000);
    return () => {
      active = false;
      window.clearInterval(timer);
      for (const c of controllers) c.abort();
    };
  }, [agentId]);

  useEffect(() => {
    const ac = new AbortController();
    let active = true;
    async function loadBehavior(signal: AbortSignal) {
      setBehavioralLoading(true);
      setBehavioralError(null);
      try {
        const row = await api.getBehavioralHash(agentId, { signal });
        if (!active) return;
        setBehavioral(row);
      } catch (err) {
        if (!active || signal.aborted) return;
        setBehavioralError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (active) setBehavioralLoading(false);
      }
    }
    loadBehavior(ac.signal);
    return () => {
      active = false;
      ac.abort();
    };
  }, [agentId]);

  useEffect(() => {
    const ac = new AbortController();
    let active = true;
    async function loadHashHistory(signal: AbortSignal) {
      setHistoryLoading(true);
      setHistoryError(null);
      try {
        const params = new URLSearchParams();
        params.set("agent_id", agentId);
        params.set("limit", "100");
        const mems = await api.memories(params);
        const recent = mems.items as MemoryListItem[];
        const events: HashTimelineEvent[] = [];
        for (const m of recent) {
          if (events.length >= 5) break;
          if (signal.aborted) break;
          const prov = await api.memoryProvenance(m.id);
          const bh = prov
            .filter((e: ProvenanceEvent) => e.event_type === "behavioral_hash_updated")
            .map((e: ProvenanceEvent) => {
              const meta = e.event_metadata as Record<string, unknown>;
              return {
                id: e.id,
                timestamp: e.timestamp,
                oldHash:
                  typeof meta.old_hash === "string" ? (meta.old_hash as string) : null,
                newHash:
                  typeof meta.new_hash === "string" ? (meta.new_hash as string) : null,
                driftScore:
                  typeof meta.drift_score === "number"
                    ? (meta.drift_score as number)
                    : null,
              };
            });
          events.push(...bh);
        }
        if (!active) return;
        events.sort((a, b) => +new Date(b.timestamp) - +new Date(a.timestamp));
        setHashEvents(events.slice(0, 5));
      } catch (err) {
        if (!active || signal.aborted) return;
        setHistoryError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (active) setHistoryLoading(false);
      }
    }
    loadHashHistory(ac.signal);
    return () => {
      active = false;
      ac.abort();
    };
  }, [agentId]);

  const driftScore = useMemo(() => {
    if (behavioral?.behavioral_drift_score != null) {
      return behavioral.behavioral_drift_score;
    }
    return agent?.behavioral_drift_score ?? 0;
  }, [agent?.behavioral_drift_score, behavioral?.behavioral_drift_score]);

  const driftLabel = useMemo(() => {
    if (driftScore < 0.2) return "Stable identity";
    if (driftScore <= 0.4) return "Moderate drift — monitoring";
    return "HIGH DRIFT — possible impersonation";
  }, [driftScore]);

  const vectorRows = useMemo(() => {
    const raw = behavioral?.behavioral_vector;
    if (!raw || typeof raw !== "object") return [];
    const wanted = [
      "avg_content_length",
      "write_interval_avg",
      "inter_agent_fraction",
      "flag_rate",
      "session_count",
    ] as const;
    return wanted
      .filter((k) => k in raw)
      .map((k) => {
        const v = (raw as Record<string, unknown>)[k];
        const n = typeof v === "number" ? v : Number(v);
        return { key: k, value: Number.isFinite(n) ? n : 0 };
      });
  }, [behavioral?.behavioral_vector]);

  async function copyHash() {
    if (!behavioral?.behavioral_hash) return;
    await navigator.clipboard.writeText(behavioral.behavioral_hash);
  }

  return (
    <aside className="fixed right-0 top-0 z-40 h-full w-96 border-l border-zinc-800 bg-zinc-950 shadow-xl">
      <div className="flex h-full flex-col">
        <div className="border-b border-zinc-800 p-4">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">Agent Detail</h2>
              <p className="text-xs text-zinc-500">{agentName}</p>
            </div>
            <Button variant="outline" onClick={onClose}>
              Close
            </Button>
          </div>
          <div className="flex gap-2">
            <Button
              variant={tab === "overview" ? "default" : "outline"}
              className="flex-1"
              onClick={() => setTab("overview")}
            >
              Overview
            </Button>
            <Button
              variant={tab === "identity" ? "default" : "outline"}
              className="flex-1"
              onClick={() => setTab("identity")}
            >
              Behavioral Identity
            </Button>
            <Button
              variant={tab === "quorum" ? "default" : "outline"}
              className="flex-1"
              onClick={() => setTab("quorum")}
            >
              Quorum Signals
            </Button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {tab === "overview" && (
            <>
              {agentLoading ? (
                <Card>
                  <LoadingSkeleton />
                </Card>
              ) : agentError ? (
                <Card>
                  <p className="text-sm text-red-400">Failed to load: {agentError}</p>
                </Card>
              ) : (
                <Card>
                  <p className="text-xs text-zinc-500">Agent</p>
                  <p className="text-sm font-medium">{agent?.name ?? agentName}</p>
                  <p className="text-xs font-mono text-zinc-500 mt-1">
                    {truncateHash(agent?.id, 18)}
                  </p>
                  <p className="text-xs text-zinc-500 mt-2">
                    Created {ago(agent?.created_at)}
                  </p>
                  <p className="text-sm mt-3">
                    Total memories: {agentStats?.memoryCount ?? 0}
                  </p>
                  <p className="text-sm">
                    System prompt hash: {truncateHash(agent?.system_prompt_hash, 20)}
                  </p>
                </Card>
              )}

              <Card>
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-sm">Behavioral drift score</p>
                  <p className="text-sm font-mono">{driftScore.toFixed(3)}</p>
                </div>
                <div className="h-2 w-full rounded bg-zinc-800">
                  <div
                    className={cn("h-2 rounded", driftColor(driftScore))}
                    style={{ width: `${Math.max(0, Math.min(1, driftScore)) * 100}%` }}
                  />
                </div>
              </Card>

              <Card>
                <p className="text-xs text-zinc-500 mb-2">DCA Context</p>
                {dcaLoading ? (
                  <LoadingSkeleton />
                ) : dcaError ? (
                  <p className="text-sm text-red-400">Failed to load</p>
                ) : (
                  dcaBadge(dca?.net_context)
                )}
              </Card>

              <Card>
                <p className="text-xs text-zinc-500 mb-2">Quorum status</p>
                {quorumLoading ? (
                  <LoadingSkeleton />
                ) : quorumError ? (
                  <p className="text-sm text-red-400">Failed to load</p>
                ) : (
                  quorumBadge(quorum?.quorum_status)
                )}
              </Card>
            </>
          )}

          {tab === "identity" && (
            <>
              <Card>
                <p className="text-xs text-zinc-500 mb-2">Behavioral Fingerprint</p>
                {behavioralLoading ? (
                  <LoadingSkeleton />
                ) : behavioralError ? (
                  <p className="text-sm text-red-400">Failed to load</p>
                ) : behavioral?.behavioral_hash ? (
                  <>
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-mono text-sm">
                        {truncateHash(behavioral.behavioral_hash, 16)}
                      </p>
                      <Button variant="outline" onClick={copyHash}>
                        Copy
                      </Button>
                    </div>
                    <p className="text-xs text-zinc-500 mt-2">
                      Last updated {ago(behavioral.behavioral_hash_updated_at)}
                    </p>
                  </>
                ) : (
                  <Badge className="bg-zinc-700/50 text-zinc-300">Not yet computed</Badge>
                )}
              </Card>

              <Card>
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-sm">Drift Score</p>
                  <p className="font-mono text-sm">{driftScore.toFixed(3)}</p>
                </div>
                <div className="h-2 w-full rounded bg-zinc-800">
                  <div
                    className={cn("h-2 rounded", driftColor(driftScore))}
                    style={{ width: `${Math.max(0, Math.min(1, driftScore)) * 100}%` }}
                  />
                </div>
                <p className="text-xs mt-2 text-zinc-500">{driftLabel}</p>
              </Card>

              <Card>
                <p className="text-sm font-medium mb-2">Behavioral Vector breakdown</p>
                {vectorRows.length === 0 ? (
                  <p className="text-xs text-zinc-500">No behavioral vector available</p>
                ) : (
                  <table className="w-full text-xs">
                    <tbody>
                      {vectorRows.map((row) => (
                        <tr key={row.key} className="border-b border-zinc-800">
                          <td className="py-1 text-zinc-400">{row.key}</td>
                          <td className="py-1 text-right font-mono">
                            {row.value.toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Card>

              <Card>
                <p className="text-sm font-medium mb-2">Hash History</p>
                {historyLoading ? (
                  <LoadingSkeleton />
                ) : historyError ? (
                  <p className="text-xs text-red-400">Failed to load</p>
                ) : hashEvents.length === 0 ? (
                  <p className="text-xs text-zinc-500">No hash change events yet</p>
                ) : (
                  <ul className="space-y-2 border-l border-zinc-700 pl-3">
                    {hashEvents.map((e) => {
                      const s = e.driftScore ?? 0;
                      const color =
                        s < 0.2 ? "text-emerald-400" : s <= 0.4 ? "text-amber-400" : "text-red-400";
                      return (
                        <li key={e.id} className="text-xs">
                          <p className={cn("font-medium", color)}>{ago(e.timestamp)}</p>
                          <p className="text-zinc-500 font-mono">
                            {truncateHash(e.oldHash, 8)} → {truncateHash(e.newHash, 8)}
                          </p>
                          <p className="text-zinc-500">drift {s.toFixed(3)}</p>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </Card>
            </>
          )}

          {tab === "quorum" && (
            <>
              {quorumLoading ? (
                <Card>
                  <LoadingSkeleton />
                </Card>
              ) : quorumError || !quorum ? (
                <Card>
                  <p className="text-sm text-red-400">Failed to load quorum signals</p>
                </Card>
              ) : (
                <>
                  <Card
                    className={cn(
                      quorum.quorum_status === "FULL_QUORUM" &&
                        "border-emerald-500/50 bg-emerald-950/20",
                      quorum.quorum_status === "PARTIAL_QUORUM" &&
                        "border-amber-500/50 bg-amber-950/20",
                      quorum.quorum_status === "FAILED_QUORUM" &&
                        "border-red-500/50 bg-red-950/20",
                    )}
                  >
                    {quorum.quorum_status === "FULL_QUORUM" && (
                      <p className="text-emerald-300">
                        ✓ Full Quorum — all three trust signals passing
                      </p>
                    )}
                    {quorum.quorum_status === "PARTIAL_QUORUM" && (
                      <p className="text-amber-300">
                        ⚠ Partial Quorum — {quorum.failing_signals.join(", ")} below
                        threshold
                      </p>
                    )}
                    {quorum.quorum_status === "FAILED_QUORUM" && (
                      <p className="text-red-300">
                        ✗ Failed Quorum — new memories from this agent set to anergic
                      </p>
                    )}
                  </Card>

                  {[
                    {
                      label: "Fast Signal",
                      subtitle: "Real-time consistency · 5-min half-life",
                      value: quorum.fast_signal,
                    },
                    {
                      label: "Medium Signal",
                      subtitle: "Session coherence · 2-hour half-life",
                      value: quorum.medium_signal,
                    },
                    {
                      label: "Slow Signal",
                      subtitle: "Historical reputation · 7-day half-life",
                      value: quorum.slow_signal,
                      note: "Minimum floor: 0.10 (reputation never fully expires)",
                    },
                  ].map((sig) => {
                    const failing =
                      quorum.failing_signals
                        .map((x) => x.toLowerCase())
                        .includes(sig.label.toLowerCase().split(" ")[0]);
                    return (
                      <Card key={sig.label}>
                        <div className="mb-1 flex items-center justify-between">
                          <p className="text-sm font-medium">{sig.label}</p>
                          <div className="flex items-center gap-2">
                            {failing && (
                              <Badge className="bg-red-500/20 text-red-300">
                                FAILING
                              </Badge>
                            )}
                            <span className="font-mono text-sm">
                              {sig.value.toFixed(2)}
                            </span>
                          </div>
                        </div>
                        <p className="text-xs text-zinc-500 mb-2">{sig.subtitle}</p>
                        <div className="relative h-2 w-full rounded bg-zinc-800">
                          <div
                            className={cn("h-2 rounded", signalColor(sig.value))}
                            style={{ width: `${Math.max(0, Math.min(1, sig.value)) * 100}%` }}
                          />
                          <div
                            className="absolute top-[-2px] h-3 border-l border-dashed border-zinc-300/70"
                            style={{ left: "60%" }}
                          />
                        </div>
                        {sig.note && <p className="text-xs text-zinc-500 mt-2">{sig.note}</p>}
                      </Card>
                    );
                  })}

                  <Card>
                    <p className="text-sm font-medium">
                      Composite: {quorum.composite_score.toFixed(3)}
                    </p>
                    <p className="text-sm text-zinc-400">
                      Trust multiplier applied to new memories: ×
                      {quorum.memory_trust_multiplier.toFixed(3)}
                    </p>
                    {quorum.failing_signals.length > 0 ? (
                      <p className="text-sm text-red-400 mt-2">
                        Failing: {quorum.failing_signals.join(" · ")}
                      </p>
                    ) : (
                      <p className="text-sm text-emerald-400 mt-2">All signals passing</p>
                    )}
                    <p className="text-xs text-zinc-500 mt-2">
                      Computed {ago(quorum.computed_at)}
                    </p>
                  </Card>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </aside>
  );
}
