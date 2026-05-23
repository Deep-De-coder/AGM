import { useEffect, useState } from "react";
import {
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  Tooltip,
} from "recharts";
import { api, type BehavioralHashResponse } from "../api";
import { Badge, Card } from "./ui";

// ─── Normalization caps ───────────────────────────────────────────────────────
// Each cap is the "maximum expected value" for that dimension.
// Values are clamped to [0, cap] then divided by cap → [0, 1].
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

type DimKey = keyof typeof CAPS;

type DimSpec = {
  key: DimKey;
  label: string;
  cap: number;
};

// These match the 10 fields in behavioral_hash.py BEHAVIORAL_VECTOR_FIELDS,
// with labels truncated to ≤12 chars.
const DIMS: DimSpec[] = [
  { key: "avg_content_length",     label: "Avg Length",  cap: CAPS.avg_content_length },
  { key: "avg_content_length_std", label: "Length Std",  cap: CAPS.avg_content_length_std },
  { key: "source_diversity",       label: "Src Divers.", cap: CAPS.source_diversity },
  { key: "avg_trust_score_written",label: "Avg Trust",   cap: CAPS.avg_trust_score_written },
  { key: "write_interval_avg",     label: "Write Intv",  cap: CAPS.write_interval_avg },
  { key: "write_interval_std",     label: "Intv Std",    cap: CAPS.write_interval_std },
  { key: "session_count",          label: "Sessions",    cap: CAPS.session_count },
  { key: "flag_rate",              label: "Flag Rate",   cap: CAPS.flag_rate },
  { key: "inter_agent_fraction",   label: "Inter-Agent", cap: CAPS.inter_agent_fraction },
  { key: "avg_safety_context_keys",label: "Safety Keys", cap: CAPS.avg_safety_context_keys },
];

// ─── Scalar extraction ────────────────────────────────────────────────────────
// source_diversity is stored as `source_type_dist` (a dict of source → fraction).
// We measure diversity as the number of distinct source types with non-zero share,
// capped at 4 → normalised to [0,1].
function toScalar(raw: Record<string, unknown>, key: string, cap: number): number {
  if (key === "source_diversity") {
    const dist = raw["source_type_dist"];
    if (dist && typeof dist === "object") {
      const nonZero = Object.values(dist as Record<string, unknown>).filter(
        (v) => typeof v === "number" && (v as number) > 0,
      ).length;
      return Math.min(nonZero / 4, 1);
    }
    return 0;
  }
  const v = raw[key];
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? Math.min(Math.max(n, 0), cap) / cap : 0;
}

// ─── Chart data row ───────────────────────────────────────────────────────────
type ChartRow = {
  dim: string;
  current: number;
  baseline: number;
};

function buildRows(
  current: Record<string, unknown>,
  baseline: Record<string, unknown>,
): ChartRow[] {
  return DIMS.map(({ key, label, cap }) => ({
    dim: label,
    current: toScalar(current, key, cap),
    baseline: toScalar(baseline, key, cap),
  }));
}

// ─── Custom tooltip ───────────────────────────────────────────────────────────
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
      <p className="mb-1 font-semibold text-zinc-300">{label}</p>
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color }}>
          {p.name}: {(p.value * 100).toFixed(0)}%
        </p>
      ))}
    </div>
  );
}

// ─── Drift score badge ────────────────────────────────────────────────────────
// Format: "Drift: 0.38"
// Green  < 0.2 · Yellow 0.2–0.4 · Red > 0.4
function DriftBadge({ score }: { score: number }) {
  const label = `Drift: ${score.toFixed(2)}`;
  if (score < 0.2) {
    return (
      <Badge className="border border-emerald-500/30 bg-emerald-500/20 text-emerald-300">
        {label}
      </Badge>
    );
  }
  if (score <= 0.4) {
    return (
      <Badge className="border border-amber-500/30 bg-amber-500/20 text-amber-300">
        {label}
      </Badge>
    );
  }
  return (
    <Badge className="animate-pulse border border-red-500/50 bg-red-600/30 text-red-200">
      {label}
    </Badge>
  );
}

// ─── Public component ─────────────────────────────────────────────────────────
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

  // ── Loading state ──────────────────────────────────────────────────────────
  if (loading) {
    return (
      <Card>
        <div className="h-[300px] w-[300px] animate-pulse rounded bg-zinc-800/50" />
      </Card>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────────
  if (error) {
    return (
      <Card>
        <p className="text-sm text-zinc-500">Behavioral data unavailable</p>
      </Card>
    );
  }

  const currentVec = (data?.behavioral_vector ?? {}) as Record<string, unknown>;
  const baselineVec = (data?.baseline_vector ?? {}) as Record<string, unknown>;
  const drift = data?.behavioral_drift_score ?? 0;
  const hasData = Object.keys(currentVec).length > 0;
  const rows = hasData ? buildRows(currentVec, baselineVec) : null;

  return (
    <Card>
      <p className="mb-3 text-sm font-medium">Behavioral Drift Profile</p>

      {!rows ? (
        <p className="text-xs text-zinc-500">
          No behavioral vector yet — write some memories first.
        </p>
      ) : (
        <>
          {/* Fixed 300×300 radar chart */}
          <RadarChart
            width={300}
            height={300}
            data={rows}
            margin={{ top: 8, right: 20, bottom: 8, left: 20 }}
          >
            <PolarGrid stroke="#3f3f46" />
            <PolarAngleAxis
              dataKey="dim"
              tick={{ fill: "#a1a1aa", fontSize: 10 }}
            />
            {/* Baseline — grey, dashed */}
            <Radar
              name="Baseline"
              dataKey="baseline"
              stroke="#9ca3af"
              fill="#9ca3af"
              fillOpacity={0.2}
              strokeWidth={1.5}
              strokeDasharray="4 2"
            />
            {/* Current — blue, solid */}
            <Radar
              name="Current"
              dataKey="current"
              stroke="#3b82f6"
              fill="#3b82f6"
              fillOpacity={0.3}
              strokeWidth={2}
            />
            <Tooltip content={<CustomTooltip />} />
          </RadarChart>

          {/* Legend */}
          <div className="mt-1 flex items-center gap-4 text-xs text-zinc-500">
            <span className="flex items-center gap-1">
              <span
                className="inline-block h-0.5 w-4 opacity-70"
                style={{ background: "#9ca3af", borderBottom: "2px dashed #9ca3af" }}
              />
              Baseline
            </span>
            <span className="flex items-center gap-1">
              <span
                className="inline-block h-0.5 w-4"
                style={{ background: "#3b82f6" }}
              />
              Current
            </span>
          </div>

          {/* Drift score badge — shown below the chart */}
          <div className="mt-3">
            <DriftBadge score={drift} />
          </div>
        </>
      )}
    </Card>
  );
}
