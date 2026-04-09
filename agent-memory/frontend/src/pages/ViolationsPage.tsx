import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Violation, type ViolationSeverity } from "../api";
import { Badge, Button, Card, cn } from "../components/ui";
import { severityBadgeClass } from "../lib/severity";

const SEVERITIES: ViolationSeverity[] = [
  "CRITICAL",
  "HIGH",
  "MEDIUM",
  "LOW",
];

function truncate(s: string, n: number) {
  if (s.length <= n) return s;
  return s.slice(0, n) + "…";
}

export function ViolationsPage() {
  const qc = useQueryClient();
  const [severity, setSeverity] = useState<ViolationSeverity | "">("");
  const [agentId, setAgentId] = useState("");
  const [ruleName, setRuleName] = useState("");
  const [unackOnly, setUnackOnly] = useState(false);
  const [selected, setSelected] = useState<Violation | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [ackName, setAckName] = useState("");

  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });

  const violations = useQuery({
    queryKey: [
      "violations",
      severity,
      agentId,
      ruleName,
      unackOnly,
    ],
    queryFn: () =>
      api.getViolations({
        severity: severity || undefined,
        agent_id: agentId || undefined,
        rule_name: ruleName || undefined,
        unacknowledged_only: unackOnly || undefined,
        limit: 500,
      }),
  });

  const summary = useQuery({
    queryKey: ["violations", "summary-counts"],
    queryFn: () => api.getViolations({ limit: 2000 }),
  });

  const countsBySeverity = useMemo(() => {
    const m: Record<ViolationSeverity, number> = {
      CRITICAL: 0,
      HIGH: 0,
      MEDIUM: 0,
      LOW: 0,
    };
    for (const v of summary.data?.items ?? []) {
      if (m[v.severity] !== undefined) m[v.severity] += 1;
    }
    return m;
  }, [summary.data?.items]);

  const ruleOptions = useMemo(() => {
    const s = new Set<string>();
    for (const v of summary.data?.items ?? []) s.add(v.rule_name);
    return [...s].sort();
  }, [summary.data?.items]);

  const acknowledge = useMutation({
    mutationFn: ({
      id,
      by,
    }: {
      id: string;
      by: string;
    }) => api.acknowledgeViolation(id, by),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["violations"] });
      setModalOpen(false);
      setSelected((sel) =>
        sel
          ? {
              ...sel,
              is_acknowledged: true,
              acknowledged_by: vars.by,
            }
          : null,
      );
      setAckName("");
    },
  });

  function submitAck() {
    if (!selected) return;
    const by = ackName.trim();
    if (!by) return;
    acknowledge.mutate({ id: selected.id, by });
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Violations</h1>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {SEVERITIES.map((sev) => (
          <Card
            key={sev}
            className={cn(
              "border",
              sev === "CRITICAL" && "border-red-500/30",
              sev === "HIGH" && "border-orange-500/30",
              sev === "MEDIUM" && "border-yellow-500/30",
              sev === "LOW" && "border-blue-500/30",
            )}
          >
            <p className="text-xs text-zinc-500 uppercase tracking-wide">{sev}</p>
            <p
              className={cn(
                "text-2xl font-semibold tabular-nums mt-1",
                sev === "CRITICAL" && "text-red-400",
                sev === "HIGH" && "text-orange-400",
                sev === "MEDIUM" && "text-yellow-400",
                sev === "LOW" && "text-blue-400",
              )}
            >
              {summary.isLoading ? "—" : countsBySeverity[sev]}
            </p>
          </Card>
        ))}
      </div>

      <Card className="flex flex-wrap gap-4 items-end">
        <label className="text-sm space-y-1">
          <span className="text-zinc-500">Severity</span>
          <select
            className="block w-44 rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm"
            value={severity}
            onChange={(e) =>
              setSeverity((e.target.value || "") as ViolationSeverity | "")
            }
          >
            <option value="">All</option>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm space-y-1">
          <span className="text-zinc-500">Agent</span>
          <select
            className="block w-56 rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm"
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
          >
            <option value="">All agents</option>
            {(agents.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name ?? a.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm space-y-1">
          <span className="text-zinc-500">Rule</span>
          <select
            className="block w-56 rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm"
            value={ruleName}
            onChange={(e) => setRuleName(e.target.value)}
          >
            <option value="">All rules</option>
            {ruleOptions.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={unackOnly}
            onChange={(e) => setUnackOnly(e.target.checked)}
            className="rounded border-zinc-600"
          />
          Unacknowledged only
        </label>
      </Card>

      <div className="overflow-x-auto rounded-xl border border-zinc-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 bg-zinc-900/50 text-left text-zinc-400">
              <th className="p-2 font-medium">Rule</th>
              <th className="p-2 font-medium">Severity</th>
              <th className="p-2 font-medium">Description</th>
              <th className="p-2 font-medium">Memory</th>
              <th className="p-2 font-medium">Agent</th>
              <th className="p-2 font-medium">Detected</th>
              <th className="p-2 font-medium">Ack</th>
            </tr>
          </thead>
          <tbody>
            {violations.isLoading && (
              <tr>
                <td colSpan={7} className="p-4 text-zinc-500">
                  Loading…
                </td>
              </tr>
            )}
            {violations.isError && (
              <tr>
                <td colSpan={7} className="p-4 text-red-400">
                  Failed to load violations. Is the API running?
                </td>
              </tr>
            )}
            {(violations.data?.items ?? []).map((v) => (
              <tr
                key={v.id}
                onClick={() => setSelected(v)}
                className={cn(
                  "border-b border-zinc-800/80 cursor-pointer hover:bg-zinc-800/40",
                  selected?.id === v.id && "bg-zinc-800/60",
                  v.is_acknowledged && "opacity-50 text-zinc-500",
                )}
              >
                <td className="p-2 font-mono text-xs">{v.rule_name}</td>
                <td className="p-2">
                  <Badge className={severityBadgeClass(v.severity)}>
                    {v.severity}
                  </Badge>
                </td>
                <td className="p-2 max-w-xs">{truncate(v.description, 80)}</td>
                <td className="p-2">
                  <Link
                    to={`/memories?memory=${encodeURIComponent(v.memory_id)}`}
                    className="text-emerald-400 hover:underline font-mono text-xs"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {v.memory_id.slice(0, 8)}…
                  </Link>
                </td>
                <td className="p-2">{v.agent_name ?? "—"}</td>
                <td className="p-2 text-zinc-500 whitespace-nowrap text-xs">
                  {new Date(v.detected_at).toLocaleString()}
                </td>
                <td className="p-2">{v.is_acknowledged ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <aside
        className={cn(
          "fixed right-0 top-0 h-full w-full max-w-md border-l border-zinc-800 bg-zinc-950/95 backdrop-blur p-6 shadow-2xl z-40 overflow-y-auto transition-transform",
          selected ? "translate-x-0" : "translate-x-full pointer-events-none",
        )}
      >
        {selected && (
          <div className="space-y-4">
            <div className="flex justify-between items-start gap-2">
              <h2 className="text-lg font-medium">Violation</h2>
              <Button variant="ghost" onClick={() => setSelected(null)}>
                Close
              </Button>
            </div>
            <Card>
              <p className="text-xs text-zinc-500 mb-1">Rule</p>
              <p className="font-mono text-sm">{selected.rule_name}</p>
            </Card>
            <Card>
              <p className="text-xs text-zinc-500 mb-1">Severity</p>
              <Badge className={severityBadgeClass(selected.severity)}>
                {selected.severity}
              </Badge>
            </Card>
            <Card>
              <p className="text-xs text-zinc-500 mb-2">Description</p>
              <p className="text-sm whitespace-pre-wrap">{selected.description}</p>
            </Card>
            <Card>
              <p className="text-xs text-zinc-500 mb-1">Memory</p>
              <Link
                className="text-emerald-400 text-sm font-mono break-all hover:underline"
                to={`/memories?memory=${encodeURIComponent(selected.memory_id)}`}
              >
                {selected.memory_id}
              </Link>
            </Card>
            <Card>
              <p className="text-xs text-zinc-500 mb-1">Agent</p>
              <p className="text-sm">{selected.agent_name ?? "—"}</p>
            </Card>
            <Card>
              <p className="text-xs text-zinc-500 mb-1">Detected</p>
              <p className="text-sm">
                {new Date(selected.detected_at).toLocaleString()}
              </p>
            </Card>
            {!selected.is_acknowledged ? (
              <Button
                className="w-full"
                onClick={() => {
                  setModalOpen(true);
                  setAckName("");
                }}
              >
                Acknowledge
              </Button>
            ) : (
              <Card>
                <p className="text-xs text-zinc-500">Acknowledged</p>
                <p className="text-sm">
                  {selected.acknowledged_by ?? "—"}
                  {selected.acknowledged_at && (
                    <span className="text-zinc-500 ml-2 text-xs">
                      {new Date(selected.acknowledged_at).toLocaleString()}
                    </span>
                  )}
                </p>
              </Card>
            )}
          </div>
        )}
      </aside>

      {modalOpen && selected && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => !acknowledge.isPending && setModalOpen(false)}
          role="presentation"
        >
          <Card
            className="w-full max-w-md space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-medium">Acknowledge violation</h3>
            <p className="text-sm text-zinc-400">
              Enter the name of the person acknowledging this violation.
            </p>
            <label className="block text-sm space-y-1">
              <span className="text-zinc-500">Acknowledged by</span>
              <input
                className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm"
                value={ackName}
                onChange={(e) => setAckName(e.target.value)}
                placeholder="Name"
                autoFocus
              />
            </label>
            <div className="flex gap-2 justify-end">
              <Button
                variant="outline"
                onClick={() => setModalOpen(false)}
                disabled={acknowledge.isPending}
              >
                Cancel
              </Button>
              <Button
                onClick={submitAck}
                disabled={!ackName.trim() || acknowledge.isPending}
              >
                {acknowledge.isPending ? "Saving…" : "Confirm"}
              </Button>
            </div>
            {acknowledge.isError && (
              <p className="text-sm text-red-400">
                {(acknowledge.error as Error).message}
              </p>
            )}
          </Card>
        </div>
      )}

      {selected && (
        <button
          type="button"
          className="fixed inset-0 z-30 bg-black/40"
          aria-label="Close panel"
          onClick={() => setSelected(null)}
        />
      )}
    </div>
  );
}
