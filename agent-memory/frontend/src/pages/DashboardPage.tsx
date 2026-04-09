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
import { Badge, Card } from "../components/ui";

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

  const s = summary.data;

  const chartData =
    history.data?.map((p) => ({
      t: new Date(p.recorded_at).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      }),
      avg: Number(p.avg_trust_score.toFixed(4)),
    })) ?? [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <p className="text-sm text-zinc-400">Total memories</p>
          <p className="text-3xl font-semibold tabular-nums">
            {summary.isLoading ? "—" : s?.total_memories ?? 0}
          </p>
        </Card>
        <Card>
          <p className="text-sm text-zinc-400">Flagged</p>
          <p className="text-3xl font-semibold tabular-nums text-red-400">
            {summary.isLoading ? "—" : s?.flagged_memories ?? 0}
          </p>
        </Card>
        <Card>
          <p className="text-sm text-zinc-400">Avg trust</p>
          <p
            className={`text-3xl font-semibold tabular-nums ${s ? trustColor(s.avg_trust_score) : ""}`}
          >
            {summary.isLoading ? "—" : s?.avg_trust_score.toFixed(3) ?? "—"}
          </p>
        </Card>
        <Card>
          <p className="text-sm text-zinc-400">Active agents</p>
          <p className="text-3xl font-semibold tabular-nums">
            {summary.isLoading ? "—" : s?.active_agents ?? 0}
          </p>
        </Card>
      </div>

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
