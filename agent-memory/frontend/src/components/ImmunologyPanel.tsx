import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { DcaStatsResponse } from "../api";
import { Button, Card, cn } from "./ui";

type ContextState = "SAFE" | "SEMI_MATURE" | "MATURE_DANGER";

interface SignalDef {
  key: string;
  label: string;
  weight: number;
}

const DANGER_SIGNALS: SignalDef[] = [
  { key: "reasoning_break", label: "Reasoning Break", weight: 0.35 },
  { key: "write_surge", label: "Write Surge", weight: 0.2 },
  { key: "source_collapse", label: "Source Collapse", weight: 0.15 },
  { key: "trust_cliff_cluster", label: "Trust Cliff Cluster", weight: 0.2 },
  { key: "retrieval_anomaly", label: "Retrieval Anomaly", weight: 0.1 },
];

const SAFE_SIGNALS: SignalDef[] = [
  { key: "consistent_reasoning", label: "Consistent Reasoning", weight: 0.3 },
  { key: "low_write_velocity", label: "Low Write Velocity", weight: 0.2 },
  { key: "source_diversity", label: "Source Diversity", weight: 0.2 },
  { key: "corroboration_rate", label: "Corroboration Rate", weight: 0.3 },
];

function secondsAgo(iso: string): number {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
}

function contextDotClass(ctx: ContextState): string {
  if (ctx === "MATURE_DANGER") return "bg-red-500 animate-pulse";
  if (ctx === "SEMI_MATURE") return "bg-amber-400";
  return "bg-emerald-400";
}

function contextBadgeClass(ctx: ContextState): string {
  if (ctx === "MATURE_DANGER")
    return "bg-red-950/60 border border-red-500/70 text-red-300";
  if (ctx === "SEMI_MATURE")
    return "bg-amber-950/60 border border-amber-500/70 text-amber-300";
  return "bg-emerald-950/60 border border-emerald-500/70 text-emerald-300";
}

function contextInterpretation(ctx: ContextState): string {
  if (ctx === "MATURE_DANGER")
    return "Threat confirmed — all new writes auto-flagged";
  if (ctx === "SEMI_MATURE")
    return "Elevated danger signals — new memories set to anergic";
  return "Agent behavior within normal parameters";
}

function SignalBar({
  label,
  triggered,
  weight,
  color,
}: {
  label: string;
  triggered: boolean;
  weight: number;
  color: "red" | "green";
}) {
  const fillPct = triggered ? weight * 100 : 0;
  const value = triggered ? weight.toFixed(2) : "0.00";
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-36 text-zinc-400 shrink-0 truncate">{label}</span>
      <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-300",
            color === "red" ? "bg-red-500" : "bg-emerald-500",
          )}
          style={{ width: `${fillPct}%` }}
        />
      </div>
      <span
        className={cn(
          "w-8 text-right tabular-nums shrink-0",
          triggered
            ? color === "red"
              ? "text-red-400"
              : "text-emerald-400"
            : "text-zinc-600",
        )}
      >
        {value}
      </span>
    </div>
  );
}

function SkeletonBars() {
  return (
    <div className="animate-pulse space-y-2">
      {Array.from({ length: 9 }, (_, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className="w-36 h-2 bg-zinc-800 rounded shrink-0" />
          <div className="flex-1 h-1.5 bg-zinc-800 rounded-full" />
          <div className="w-8 h-2 bg-zinc-800 rounded" />
        </div>
      ))}
    </div>
  );
}

export function ImmunologyPanel() {
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [secondsSinceScan, setSecondsSinceScan] = useState<number | null>(null);
  const [scanLoading, setScanLoading] = useState(false);

  const agentsQuery = useQuery({
    queryKey: ["agents"],
    queryFn: api.agents,
    refetchInterval: 60_000,
    refetchOnWindowFocus: false,
  });

  const agents = agentsQuery.data ?? [];
  const activeAgentId = selectedAgentId ?? agents[0]?.id ?? null;

  const dcaQuery = useQuery({
    queryKey: ["dca", activeAgentId],
    queryFn: () => api.getStatsDca(activeAgentId as string),
    enabled: activeAgentId !== null,
    refetchInterval: 15_000,
    refetchOnWindowFocus: false,
  });

  // Tick "seconds ago" every second; cleanup stops when component unmounts
  useEffect(() => {
    const sampledAt = dcaQuery.data?.sampled_at;
    if (!sampledAt) {
      setSecondsSinceScan(null);
      return;
    }
    setSecondsSinceScan(secondsAgo(sampledAt));
    const id = setInterval(() => {
      setSecondsSinceScan(secondsAgo(sampledAt));
    }, 1000);
    return () => clearInterval(id);
  }, [dcaQuery.data?.sampled_at]);

  const dca: DcaStatsResponse | undefined = dcaQuery.data;
  const headerCtx: ContextState = dca?.net_context ?? "SAFE";
  const isLive = activeAgentId !== null && !dcaQuery.isError;

  function handleManualScan() {
    setScanLoading(true);
    api
      .runTrustDecay()
      .then(() => dcaQuery.refetch())
      .catch(() => undefined)
      .finally(() => setScanLoading(false));
  }

  if (agentsQuery.isLoading) {
    return (
      <Card>
        <div className="animate-pulse space-y-3">
          <div className="h-4 bg-zinc-800 rounded w-56" />
          <SkeletonBars />
        </div>
      </Card>
    );
  }

  if (agentsQuery.isError) {
    return (
      <Card>
        <p className="text-sm text-zinc-500">
          DCA data unavailable — is the backend running?
        </p>
      </Card>
    );
  }

  if (agents.length === 0) {
    return (
      <Card>
        <p className="text-sm text-zinc-500">
          No agents registered. Use{" "}
          <code className="text-emerald-400">register_agent</code> to add
          agents.
        </p>
      </Card>
    );
  }

  return (
    <Card>
      {/* Keyframe for MATURE_DANGER scale pulse */}
      <style>{`
        @keyframes danger-scale {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(1.05); }
        }
        .animate-danger-pulse {
          animation: danger-scale 1.5s ease-in-out infinite;
        }
      `}</style>

      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <span
          className={cn(
            "inline-block w-2 h-2 rounded-full shrink-0",
            contextDotClass(headerCtx),
          )}
        />
        <h2 className="text-sm font-medium text-zinc-200">
          Immunology Control Panel
        </h2>
        {isLive && (
          <span className="flex items-center gap-1 text-xs text-zinc-500 ml-1">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            live
          </span>
        )}
      </div>

      {/* Agent selector tabs */}
      <div className="flex gap-1 flex-wrap mb-4">
        {agents.map((agent) => (
          <button
            key={agent.id}
            type="button"
            onClick={() => setSelectedAgentId(agent.id)}
            className={cn(
              "px-3 py-1 rounded-md text-xs font-medium transition-colors",
              activeAgentId === agent.id
                ? "bg-zinc-700 text-zinc-100"
                : "bg-zinc-800/60 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200",
            )}
          >
            {agent.name}
          </button>
        ))}
      </div>

      {/* Body */}
      {dcaQuery.isLoading ? (
        <SkeletonBars />
      ) : dcaQuery.isError ? (
        <p className="text-sm text-zinc-500">
          DCA data unavailable — is the backend running?
        </p>
      ) : dca != null ? (
        <div className="grid gap-6 sm:grid-cols-2">
          {/* LEFT: Signal bars */}
          <div className="space-y-3">
            <p className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
              Danger Signals
            </p>
            <div className="space-y-2">
              {DANGER_SIGNALS.map((sig) => (
                <SignalBar
                  key={sig.key}
                  label={sig.label}
                  triggered={dca.triggered_dangers.includes(sig.key)}
                  weight={sig.weight}
                  color="red"
                />
              ))}
            </div>
            <div className="border-t border-zinc-800 pt-3">
              <p className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider mb-2">
                Safe Signals
              </p>
              <div className="space-y-2">
                {SAFE_SIGNALS.map((sig) => (
                  <SignalBar
                    key={sig.key}
                    label={sig.label}
                    triggered={dca.triggered_safes.includes(sig.key)}
                    weight={sig.weight}
                    color="green"
                  />
                ))}
              </div>
            </div>
          </div>

          {/* RIGHT: Context state */}
          <div className="flex flex-col items-center justify-center gap-3 py-2">
            <span
              className={cn(
                "px-5 py-2.5 rounded-lg text-sm font-semibold tracking-wide",
                contextBadgeClass(dca.net_context),
                dca.net_context === "MATURE_DANGER" && "animate-danger-pulse",
              )}
            >
              {dca.net_context}
            </span>
            <p className="text-xs text-zinc-500">
              Last scan:{" "}
              {secondsSinceScan !== null ? `${secondsSinceScan}s ago` : "—"}
            </p>
            <p className="text-xs text-zinc-400 text-center max-w-48 leading-relaxed">
              {contextInterpretation(dca.net_context)}
            </p>
            <p className="text-[10px] text-zinc-600 tabular-nums">
              D {dca.danger_score.toFixed(2)} · S {dca.safe_score.toFixed(2)}
            </p>
          </div>
        </div>
      ) : null}

      {/* Footer */}
      <div className="mt-4 pt-3 border-t border-zinc-800 flex items-center justify-between">
        <p className="text-xs text-zinc-600">DCA scans every 3 minutes</p>
        <Button
          variant="outline"
          onClick={handleManualScan}
          disabled={scanLoading}
          className="text-xs h-7 px-2"
        >
          {scanLoading ? "Scanning…" : "Run Manual Scan"}
        </Button>
      </div>
    </Card>
  );
}
