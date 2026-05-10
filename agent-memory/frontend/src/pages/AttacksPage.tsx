import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, ShieldAlert, XCircle } from "lucide-react";
import { api, type AttackSimResult, type NotificationItem } from "../api";
import { Badge, Button, Card, cn } from "../components/ui";
import { severityBadgeClass } from "../lib/severity";

// ── static attack catalogue ───────────────────────────────────────────────────

type AttackSeverity = "CRITICAL" | "HIGH";

interface AttackMeta {
  key: string;
  name: string;
  desc: string;
  severity: AttackSeverity;
  mechanism: string;
  expectedRules: string[];
}

const ATTACKS: AttackMeta[] = [
  {
    key: "sleeper_cell",
    name: "The Sleeper Cell",
    desc: "Agent writes 20 legitimate memories, then activates a drifted behavioral pattern. Tests whether slow-burn identity compromise is caught before consolidation.",
    severity: "CRITICAL",
    mechanism: "Behavioral Hash + DCA",
    expectedRules: ["RULE_011"],
  },
  {
    key: "echo_chamber",
    name: "The Echo Chamber",
    desc: "Concurrent read-modify-write race on a high-value memory. Attempts content injection without a provenance record by exploiting retrieval timing.",
    severity: "HIGH",
    mechanism: "Reconsolidation Lock",
    expectedRules: ["RULE_004"],
  },
  {
    key: "reputation_laundering",
    name: "The Reputation Laundering Relay",
    desc: "Low-trust poison is routed through a trusted relay agent to bypass direct trust filters. Tests whether chain contamination propagates undetected.",
    severity: "CRITICAL",
    mechanism: "Quorum + RULE_002",
    expectedRules: ["RULE_002"],
  },
  {
    key: "temporal_phantom",
    name: "The Temporal Phantom",
    desc: "Memory claims to be a consequence of events that never occurred. Tests causal-orphan detection and vector-clock validation.",
    severity: "HIGH",
    mechanism: "RULE_012 + Causal Validation",
    expectedRules: ["RULE_012"],
  },
  {
    key: "anergy_escape",
    name: "The Anergy Escape",
    desc: "Three coordinated witnesses attempt artificial co-stimulation of a quarantined memory to force its promotion back to active state.",
    severity: "CRITICAL",
    mechanism: "RULE_013 + Two-Signal Anergy",
    expectedRules: ["RULE_013"],
  },
  {
    key: "identity_ghost",
    name: "The Identity Ghost",
    desc: "Perfect behavioral mimic of a legitimate agent with no reputation history. Tests whether the quorum slow-signal gap and behavioral hash catch impersonation.",
    severity: "HIGH",
    mechanism: "Quorum Slow Signal + Behavioral Hash",
    expectedRules: ["RULE_011"],
  },
  {
    key: "consolidation_hijack",
    name: "The Consolidation Hijack",
    desc: "Contradictory memories injected after a target reaches consolidated state. Tests content-address integrity and contradiction detection on locked memories.",
    severity: "HIGH",
    mechanism: "Content Address + RULE_003",
    expectedRules: ["RULE_003"],
  },
];

// ── sub-components ────────────────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: AttackSeverity }) {
  const cls =
    severity === "CRITICAL"
      ? "bg-red-500/20 text-red-300 border border-red-500/40"
      : "bg-orange-500/20 text-orange-300 border border-orange-500/40";
  return <Badge className={cls}>{severity}</Badge>;
}

function AttackCard({
  attack,
  selected,
  running,
  onRun,
}: {
  attack: AttackMeta;
  selected: boolean;
  running: boolean;
  onRun: (key: string) => void;
}) {
  return (
    <Card
      className={cn(
        "flex flex-col gap-3 transition-colors",
        selected ? "border-red-500/60 bg-red-950/20" : "hover:border-zinc-600",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="font-semibold text-sm leading-snug">{attack.name}</p>
        <SeverityBadge severity={attack.severity} />
      </div>
      <p className="text-xs text-zinc-400 leading-relaxed flex-1">{attack.desc}</p>
      <p className="text-xs text-zinc-500 font-mono">
        Defense: {attack.mechanism}
      </p>
      <Button
        className={cn(
          "w-full mt-auto text-xs",
          selected && running
            ? "bg-zinc-700 text-zinc-400"
            : "bg-red-700 hover:bg-red-600 text-white",
        )}
        disabled={running}
        onClick={() => onRun(attack.key)}
      >
        {selected && running ? "Running…" : "Run Attack"}
      </Button>
    </Card>
  );
}

function StepItem({ text, index }: { text: string; index: number }) {
  return (
    <div className="flex items-start gap-2 text-sm">
      <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />
      <span className="text-zinc-300">
        <span className="text-zinc-500 mr-1">{index + 1}.</span>
        {text}
      </span>
    </div>
  );
}

function NotifItem({ n }: { n: NotificationItem }) {
  const cls = severityBadgeClass(n.severity);
  return (
    <div className="flex items-start gap-2 text-xs border-b border-zinc-800/60 pb-2 last:border-0">
      <Badge className={cn(cls, "shrink-0 mt-0.5")}>{n.severity}</Badge>
      <div className="min-w-0">
        <p className="font-medium text-zinc-200 truncate">{n.title}</p>
        <p className="text-zinc-500 mt-0.5 leading-snug">{n.message}</p>
      </div>
    </div>
  );
}

// ── main page ─────────────────────────────────────────────────────────────────

export function AttacksPage() {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [agentId, setAgentId] = useState("");
  const [result, setResult] = useState<AttackSimResult | null>(null);
  const [liveNotifs, setLiveNotifs] = useState<NotificationItem[]>([]);
  const runStartRef = useRef<Date | null>(null);

  const agentsQ = useQuery({ queryKey: ["agents"], queryFn: api.agents });

  const mutation = useMutation({
    mutationFn: ({ key }: { key: string }) =>
      api.runAttackSimulation(key, agentId),
    onSuccess: (data) => {
      setResult(data);
    },
  });

  const isRunning = mutation.isPending;

  // Poll notifications while attack is running
  useEffect(() => {
    if (!isRunning) return;
    const poll = async () => {
      try {
        const notifs = await api.getNotifications();
        const start = runStartRef.current;
        const fresh = start
          ? notifs.filter((n) => new Date(n.created_at) >= start)
          : notifs;
        setLiveNotifs(fresh);
      } catch {
        // swallow — backend may be busy
      }
    };
    poll();
    const id = setInterval(() => void poll(), 2000);
    return () => clearInterval(id);
  }, [isRunning]);

  function handleRun(key: string) {
    setSelectedKey(key);
    setResult(null);
    setLiveNotifs([]);
    runStartRef.current = new Date();
    mutation.mutate({ key });
  }

  const resetMut = useMutation({
    mutationFn: api.resetDemoData,
    onSuccess: () => {
      setResult(null);
      setLiveNotifs([]);
      setSelectedKey(null);
    },
  });

  const selectedMeta = ATTACKS.find((a) => a.key === selectedKey);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <ShieldAlert className="h-6 w-6 text-red-400" />
        <h1 className="text-2xl font-semibold tracking-tight">Attack Simulations</h1>
      </div>

      {/* warning banner */}
      <div className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-950/30 px-4 py-3 text-sm text-amber-300">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        <span>
          <strong>Simulation Mode</strong> — these attacks run against real backend
          data. Reset after each run to avoid state bleed between simulations.
        </span>
      </div>

      <div className="flex flex-col lg:flex-row gap-6 min-h-0">
        {/* ── LEFT: attack selector ── */}
        <div className="lg:w-[44%] space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2 gap-3">
            {ATTACKS.map((a) => (
              <AttackCard
                key={a.key}
                attack={a}
                selected={selectedKey === a.key}
                running={isRunning && selectedKey === a.key}
                onRun={handleRun}
              />
            ))}
          </div>

          {/* agent selector */}
          <Card className="space-y-2">
            <p className="text-xs text-zinc-500">
              Agent context (passed to simulation)
            </p>
            <select
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              disabled={isRunning}
            >
              <option value="">— none / auto —</option>
              {(agentsQ.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            <p className="text-xs text-zinc-600">
              Attacks create their own ATTACK_ agents. This field is for
              additional context only.
            </p>
          </Card>
        </div>

        {/* ── RIGHT: live feed ── */}
        <div className="flex-1 space-y-4">
          {!selectedKey && !result && (
            <Card className="flex flex-col items-center justify-center py-16 text-center gap-3">
              <ShieldAlert className="h-10 w-10 text-zinc-700" />
              <p className="text-zinc-500 text-sm">
                Select an attack on the left to begin a simulation.
              </p>
            </Card>
          )}

          {/* running indicator */}
          {isRunning && selectedMeta && (
            <Card className="border-red-500/30 bg-red-950/10">
              <div className="flex items-center gap-3">
                <span className="relative flex h-3 w-3">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-3 w-3 bg-red-500" />
                </span>
                <p className="text-sm font-medium text-red-300">
                  Running: {selectedMeta.name}
                </p>
              </div>
              <p className="text-xs text-zinc-500 mt-2">
                Defense mechanism: {selectedMeta.mechanism}
              </p>
            </Card>
          )}

          {/* result */}
          {result && (
            <Card
              className={cn(
                "border",
                result.caught
                  ? "border-emerald-500/40 bg-emerald-950/10"
                  : "border-red-500/40 bg-red-950/10",
              )}
            >
              <div className="flex items-center gap-2 mb-3">
                {result.caught ? (
                  <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                ) : (
                  <XCircle className="h-5 w-5 text-red-400" />
                )}
                <p
                  className={cn(
                    "font-semibold text-sm",
                    result.caught ? "text-emerald-300" : "text-red-300",
                  )}
                >
                  {result.caught ? "Attack caught" : "Partial bypass"} —{" "}
                  {result.attack}
                </p>
              </div>
              {result.evidence && (
                <p className="text-xs text-zinc-400 font-mono mb-3">
                  Evidence: {result.evidence}
                </p>
              )}

              {/* rules triggered */}
              {result.rules_triggered.length > 0 && (
                <div className="mb-3">
                  <p className="text-xs text-zinc-500 mb-1.5">Rules triggered</p>
                  <div className="flex flex-wrap gap-1.5">
                    {result.rules_triggered.map((r) => (
                      <Badge
                        key={r}
                        className="bg-red-500/20 text-red-300 border border-red-500/40 font-mono"
                      >
                        {r}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {/* steps */}
              {result.steps.length > 0 && (
                <div>
                  <p className="text-xs text-zinc-500 mb-2">Steps</p>
                  <div className="space-y-1.5 max-h-56 overflow-y-auto pr-1">
                    {result.steps.map((s, i) => (
                      <StepItem key={i} text={s} index={i} />
                    ))}
                  </div>
                </div>
              )}
            </Card>
          )}

          {/* live notifications */}
          {(isRunning || liveNotifs.length > 0) && (
            <Card>
              <p className="text-xs text-zinc-500 mb-2">
                {isRunning
                  ? "Live notifications (polling every 2s)"
                  : "Notifications during run"}
              </p>
              {liveNotifs.length === 0 ? (
                <p className="text-xs text-zinc-600 italic">
                  Waiting for defense signals…
                </p>
              ) : (
                <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                  {liveNotifs.map((n) => (
                    <NotifItem key={n.id} n={n} />
                  ))}
                </div>
              )}
            </Card>
          )}

          {/* mutation error */}
          {mutation.isError && (
            <Card className="border-red-500/40">
              <p className="text-sm text-red-400">
                {(mutation.error as Error).message}
              </p>
            </Card>
          )}

          {/* reset */}
          {(result ?? isRunning) && (
            <div className="flex justify-end pt-2">
              <Button
                variant="outline"
                className="text-xs border-zinc-700"
                disabled={isRunning || resetMut.isPending}
                onClick={() => resetMut.mutate()}
              >
                {resetMut.isPending
                  ? "Resetting…"
                  : "Reset Demo Data"}
              </Button>
              {resetMut.isSuccess && (
                <span className="ml-3 text-xs text-emerald-400 self-center">
                  Cleared.
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
