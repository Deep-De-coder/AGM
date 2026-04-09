import { useQuery } from "@tanstack/react-query";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import { Badge, Card, cn } from "../components/ui";

function trustColor(score: number) {
  if (score > 0.7) return "text-emerald-400";
  if (score >= 0.4) return "text-amber-400";
  return "text-red-400";
}

export function DashboardPage() {
  const summary = useQuery({
    queryKey: ["summary"],
    queryFn: api.summary,
    refetchInterval: 30_000,
  });

  const history = useQuery({
    queryKey: ["trust-history"],
    queryFn: () => api.trustHistory(24),
    refetchInterval: 30_000,
  });

  const activeViolations = useQuery({
    queryKey: ["violations", "dashboard-unack"],
    queryFn: () => api.getViolations({ unacknowledged_only: true, limit: 1 }),
    refetchInterval: 30_000,
    retry: false,
  });

  const critical24h = useQuery({
    queryKey: ["violations", "dashboard-critical-24h"],
    queryFn: async () => {
      const r = await api.getViolations({ severity: "CRITICAL", limit: 500 });
      const cutoff = Date.now() - 24 * 60 * 60 * 1000;
      return r.items.filter(
        (v) => new Date(v.detected_at).getTime() >= cutoff,
      ).length;
    },
    refetchInterval: 30_000,
    retry: false,
  });

  const s = summary.data;

  const chartData =
    history.data?.map((p) => ({
      t: new Date(p.timestamp).toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }),
      avg: Number(p.average_trust_score.toFixed(4)),
    })) ?? [];

  const unackTotal = activeViolations.data?.total ?? 0;
  const criticalCount = critical24h.data ?? 0;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card>
          <p className="text-sm text-zinc-400">Total memories</p>
          <p className="text-3xl font-semibold tabular-nums">
            {summary.isLoading ? "—" : s?.total_memories ?? 0}
          </p>
        </Card>
        <Card>
          <p className="text-sm text-zinc-400">Flagged</p>
          <p className="text-3xl font-semibold tabular-nums text-red-400">
            {summary.isLoading ? "—" : s?.flagged_count ?? 0}
          </p>
        </Card>
        <Card>
          <p className="text-sm text-zinc-400">Avg trust</p>
          <p
            className={`text-3xl font-semibold tabular-nums ${s ? trustColor(s.average_trust_score) : ""}`}
          >
            {summary.isLoading ? "—" : s?.average_trust_score.toFixed(3) ?? "—"}
          </p>
        </Card>
        <Card>
          <p className="text-sm text-zinc-400">Active agents</p>
          <p className="text-3xl font-semibold tabular-nums">
            {summary.isLoading ? "—" : s?.active_agents_count ?? 0}
          </p>
        </Card>
        <Card>
          <p className="text-sm text-zinc-400">Active violations</p>
          <p
            className={cn(
              "text-3xl font-semibold tabular-nums",
              activeViolations.isError && "text-zinc-500",
              !activeViolations.isError && unackTotal > 0 && "text-red-400",
              !activeViolations.isError && unackTotal === 0 && "text-zinc-100",
            )}
          >
            {activeViolations.isLoading
              ? "—"
              : activeViolations.isError
                ? "—"
                : unackTotal}
          </p>
          {activeViolations.isError && (
            <p className="text-xs text-zinc-500 mt-1">API unavailable</p>
          )}
        </Card>
        <Card>
          <p className="text-sm text-zinc-400">Critical alerts (24h)</p>
          <p
            className={cn(
              "text-3xl font-semibold tabular-nums",
              critical24h.isError && "text-zinc-500",
              !critical24h.isError &&
                criticalCount > 0 &&
                "text-red-400 animate-pulse",
              !critical24h.isError && criticalCount === 0 && "text-zinc-100",
            )}
          >
            {critical24h.isLoading
              ? "—"
              : critical24h.isError
                ? "—"
                : criticalCount}
          </p>
          {critical24h.isError && (
            <p className="text-xs text-zinc-500 mt-1">API unavailable</p>
          )}
        </Card>
      </div>

      {(s?.dca || s?.quorum_health || s?.integrity) && (
        <div className="grid gap-4 sm:grid-cols-3">
          {s?.dca && (
            <Card>
              <p className="text-sm text-zinc-400">Dendritic cell scan</p>
              <p className="text-xs text-zinc-500 mt-1">
                Last:{" "}
                {s.dca.last_scan_at
                  ? new Date(s.dca.last_scan_at).toLocaleString()
                  : "—"}
              </p>
              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                <span className="text-emerald-400">
                  SAFE {s.dca.agents_safe}
                </span>
                <span className="text-amber-400">
                  SEMI {s.dca.agents_semi_mature}
                </span>
                <span className="text-red-400">
                  DANGER {s.dca.agents_in_danger}
                </span>
              </div>
              {s.dca.agents_in_danger > 0 && (
                <p className="mt-2 text-sm text-red-300 animate-pulse">
                  Agent(s) in MATURE_DANGER — review flagged memories.
                </p>
              )}
            </Card>
          )}
          {s?.quorum_health && (
            <Card>
              <p className="text-sm text-zinc-400">Quorum health</p>
              <p className="text-xs text-zinc-500 mt-1">
                Full {s.quorum_health.full_quorum_agents} · Partial{" "}
                {s.quorum_health.partial_quorum_agents} · Failed{" "}
                {s.quorum_health.failed_quorum_agents}
              </p>
            </Card>
          )}
          {s?.integrity && (
            <Card>
              <p className="text-sm text-zinc-400">Storage integrity</p>
              <p
                className={cn(
                  "text-2xl font-semibold tabular-nums mt-1",
                  s.integrity.verified < s.integrity.total_with_hash
                    ? "text-red-400"
                    : "text-emerald-400",
                )}
              >
                {s.integrity.verified} / {s.integrity.total_with_hash}
              </p>
              <p className="text-xs text-zinc-500 mt-1">
                Memories with valid content hash
              </p>
            </Card>
          )}
        </div>
      )}

      {s?.danger_signals && (
        <>
          {(() => {
            const ds = s.danger_signals;
            const anyBreached =
              ds.anergy_threshold_breached ||
              ds.diversity_threshold_breached ||
              ds.coherence_threshold_breached;
            return (
              <>
                {anyBreached && (
                  <div className="rounded-lg border border-red-500/50 bg-red-950/40 px-4 py-3 text-sm text-red-200">
                    ⚠ Danger signal threshold breached — check notifications for
                    details
                  </div>
                )}
                <div>
                  <h2 className="text-lg font-medium text-zinc-200 mb-3">
                    System Health
                  </h2>
                  <div className="grid gap-4 sm:grid-cols-3">
                    <Card>
                      <p className="text-sm text-zinc-400">Anergy Ratio</p>
                      <p
                        className={`text-2xl font-semibold tabular-nums ${
                          ds.anergy_threshold_breached
                            ? "text-red-400"
                            : "text-emerald-400"
                        }`}
                      >
                        {(ds.anergy_ratio * 100).toFixed(1)}%
                      </p>
                      <p className="text-xs text-zinc-500 mt-1">
                        Unvalidated memory accumulation
                      </p>
                    </Card>
                    <Card>
                      <p className="text-sm text-zinc-400">Source Diversity</p>
                      <p
                        className={`text-2xl font-semibold tabular-nums ${
                          ds.diversity_threshold_breached
                            ? "text-red-400"
                            : "text-emerald-400"
                        }`}
                      >
                        {ds.source_diversity_index.toFixed(2)}
                      </p>
                      <p className="text-xs text-zinc-500 mt-1">
                        Memory source entropy (0–1)
                      </p>
                    </Card>
                    <Card>
                      <p className="text-sm text-zinc-400">Reasoning Coherence</p>
                      <p
                        className={`text-2xl font-semibold tabular-nums ${
                          ds.coherence_threshold_breached
                            ? "text-red-400"
                            : "text-emerald-400"
                        }`}
                      >
                        {ds.reasoning_coherence.toFixed(2)}
                      </p>
                      <p className="text-xs text-zinc-500 mt-1">
                        Consecutive memory similarity
                      </p>
                    </Card>
                  </div>
                </div>
              </>
            );
          })()}
        </>
      )}

      {s?.memories_by_source_type &&
        Object.keys(s.memories_by_source_type).length > 0 && (
          <Card>
            <p className="text-sm font-medium text-zinc-300 mb-2">
              Memories by source type
            </p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(s.memories_by_source_type).map(([k, v]) => (
                <Badge key={k} className="bg-zinc-800 text-zinc-300">
                  {k}: {String(v)}
                </Badge>
              ))}
            </div>
          </Card>
        )}

      <Card className="h-80">
        <div className="flex items-center justify-between mb-2">
          <p className="text-sm font-medium text-zinc-300">
            Avg trust (24h, polls every 30s)
          </p>
          {history.data && history.data.length > 0 && (
            <Badge className="bg-zinc-800 text-zinc-300">
              {history.data.length} samples
            </Badge>
          )}
        </div>
        {chartData.length === 0 ? (
          <p className="text-zinc-500 text-sm py-8 text-center">
            No snapshots yet. Run the trust engine (background task or POST{" "}
            <code className="text-emerald-400">/admin/run-trust-decay</code>) to
            populate history.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height="90%">
            <LineChart data={chartData}>
              <XAxis dataKey="t" stroke="#71717a" fontSize={11} />
              <YAxis
                domain={[0, 1]}
                stroke="#71717a"
                fontSize={11}
                tickFormatter={(v) => v.toFixed(2)}
              />
              <Tooltip
                contentStyle={{
                  background: "#18181b",
                  border: "1px solid #3f3f46",
                }}
              />
              <Line
                type="monotone"
                dataKey="avg"
                stroke="#34d399"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </Card>
    </div>
  );
}
