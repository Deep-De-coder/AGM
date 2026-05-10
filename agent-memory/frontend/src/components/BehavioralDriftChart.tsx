import { useEffect, useState } from "react";
import {
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { api, type BehavioralHashResponse } from "../api";
import { Badge, Card } from "./ui";
import { cn } from "./ui";

type DimSpec = {
  key: keyof typeof CAPS;
  label: string;
  cap: number;
};

const CAPS = {
  avg_content_length: 1000,
  avg_content_length_std: 500,
  source_diversity: 1,
  avg_trust_score_written: 1,
  write_interval_avg: 3600,
  write_interval_std: 1800,
  session_count: 50,
  flag_rate: 1,
  inter_agent_fraction: 1,
  avg_safety_context_keys: 10,
} as const;

const DIMS: DimSpec[] = [
  { key: "avg_content_length", label: "Avg Length", cap: CAPS.avg_content_length },
  { key: "avg_content_length_std", label: "Length Std", cap: CAPS.avg_content_length_std },
  { key: "source_diversity", label: "Src Divers.", cap: CAPS.source_diversity },
  { key: "avg_trust_score_written", label: "Avg Trust", cap: CAPS.avg_trust_score_written },
  { key: "write_interval_avg", label: "Write Intv", cap: CAPS.write_interval_avg },
  { key: "write_interval_std", label: "Intv Std", cap: CAPS.write_interval_std },
  { key: "session_count", label: "Sessions", cap: CAPS.session_count },
  { key: "flag_rate", label: "Flag Rate", cap: CAPS.flag_rate },
  { key: "inter_agent_fraction", label: "Inter-Agent", cap: CAPS.inter_agent_fraction },
  { key: "avg_safety_context_keys", label: "Safety Keys", cap: CAPS.avg_safety_context_keys },
];

function toScalar(raw: Record<string, unknown>, key: string, cap: number): number {
  if (key === "source_diversity") {
    const dist = raw["source_type_dist"];
    if (dist && typeof dist === "object") {
      const count = Object.values(dist as Record<string, unknown>).filter(
        (v) => typeof v === "number" && (v as number) > 0
      ).length;
      return Math.min(count / 4, 1);
    }
    return 0;
  }
  const v = raw[key];
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? Math.min(Math.max(n, 0), cap) / cap : 0;
}

type ChartRow = {
  dim: string;
  current: number;
  baseline: number;
};

function buildRows(
  current: Record<string, unknown>,
  baseline: Record<string, unknown>
): ChartRow[] {
  return DIMS.map(({ key, label, cap }) => ({
    dim: label,
    current: toScalar(current, key, cap),
    baseline: toScalar(baseline, key, cap),
  }));
}

type TooltipPayloadItem = {
  name: string;
  value: number;
  color: string;
};

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs shadow-lg">
      <p className="font-semibold text-zinc-300 mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color }}>
          {p.name}: {(p.value * 100).toFixed(0)}%
        </p>
      ))}
    </div>
  );
}

function driftBadge(score: number) {
  if (score < 0.2)
    return (
      <Badge className="bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
        Stable — drift {score.toFixed(3)}
      </Badge>
    );
  if (score <= 0.4)
    return (
      <Badge className="bg-amber-500/20 text-amber-300 border border-amber-500/30">
        Moderate drift — {score.toFixed(3)}
      </Badge>
    );
  return (
    <Badge className="animate-pulse bg-red-600/30 text-red-200 border border-red-500/50">
      HIGH DRIFT — {score.toFixed(3)}
    </Badge>
  );
}

type Props = { agentId: string };

export default function BehavioralDriftChart({ agentId }: Props) {
  const [data, setData] = useState<BehavioralHashResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .getBehavioralHash(agentId, { signal: ac.signal })
      .then((r) => {
        if (!active) return;
        setData(r);
      })
      .catch((err: unknown) => {
        if (!active || ac.signal.aborted) return;
        setError(err instanceof Error ? err.message : "Failed to load");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      ac.abort();
    };
  }, [agentId]);

  if (loading) {
    return (
      <Card>
        <div className="space-y-2">
          <div className="h-3 w-1/2 animate-pulse rounded bg-zinc-800" />
          <div className="h-48 animate-pulse rounded bg-zinc-800/50" />
        </div>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <p className="text-sm text-red-400">Failed to load behavioral profile: {error}</p>
      </Card>
    );
  }

  const currentVec = (data?.behavioral_vector as Record<string, unknown> | null) ?? {};
  const baselineVec = (data?.baseline_vector as Record<string, unknown> | null) ?? {};
  const drift = data?.behavioral_drift_score ?? 0;
  const hasData = Object.keys(currentVec).length > 0;

  const rows = hasData ? buildRows(currentVec, baselineVec) : null;

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-medium">Behavioral Drift Profile</p>
        {driftBadge(drift)}
      </div>

      {!rows ? (
        <p className="text-xs text-zinc-500">No behavioral vector yet — write some memories first.</p>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <RadarChart data={rows} margin={{ top: 8, right: 20, bottom: 8, left: 20 }}>
            <PolarGrid stroke="#3f3f46" />
            <PolarAngleAxis
              dataKey="dim"
              tick={{ fill: "#a1a1aa", fontSize: 10 }}
            />
            <Radar
              name="Baseline"
              dataKey="baseline"
              stroke="#6366f1"
              fill="#6366f1"
              fillOpacity={0.15}
              strokeWidth={1.5}
              strokeDasharray="4 2"
            />
            <Radar
              name="Current"
              dataKey="current"
              stroke="#10b981"
              fill="#10b981"
              fillOpacity={0.25}
              strokeWidth={2}
            />
            <Tooltip
              content={
                <CustomTooltip />
              }
            />
          </RadarChart>
        </ResponsiveContainer>
      )}

      <div
        className={cn(
          "flex items-center gap-4 mt-2 text-xs text-zinc-500",
          !rows && "hidden"
        )}
      >
        <span className="flex items-center gap-1">
          <span className="inline-block h-0.5 w-4 bg-indigo-400 opacity-70 border-dashed" />
          Baseline
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-0.5 w-4 bg-emerald-400" />
          Current
        </span>
      </div>
    </Card>
  );
}
