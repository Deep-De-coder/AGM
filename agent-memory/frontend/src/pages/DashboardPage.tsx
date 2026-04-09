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
