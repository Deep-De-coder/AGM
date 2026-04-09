import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api, type MemoryListItem } from "../api";
import { Badge, Button, Card, cn } from "../components/ui";
import { severityBadgeClass } from "../lib/severity";

function preview(s: string, n = 50) {
  if (s.length <= n) return s;
  return s.slice(0, n) + "…";
}

function trustBadge(score: number) {
  if (score > 0.7)
    return (
      <Badge className="bg-emerald-500/20 text-emerald-300">
        {score.toFixed(3)}
      </Badge>
    );
  if (score >= 0.4)
    return (
      <Badge className="bg-amber-500/20 text-amber-300">
        {score.toFixed(3)}
      </Badge>
    );
  return (
    <Badge className="bg-red-500/20 text-red-300">{score.toFixed(3)}</Badge>
  );
}

export function MemoriesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [agentId, setAgentId] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [minTrust, setMinTrust] = useState(0);
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    const m = searchParams.get("memory");
    setSelectedId(m);
  }, [searchParams]);

  function selectMemory(id: string) {
    setSelectedId(id);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("memory", id);
      return next;
    });
  }

  function closeDetail() {
    setSelectedId(null);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("memory");
      return next;
    });
  }

  const params = useMemo(() => {
    const p = new URLSearchParams();
    p.set("limit", "100");
    if (agentId.trim()) p.set("agent_id", agentId.trim());
    if (sourceType.trim()) p.set("source_type", sourceType.trim());
    p.set("min_trust_score", String(minTrust));
    if (flaggedOnly) p.set("flagged_only", "true");
    return p;
  }, [agentId, sourceType, minTrust, flaggedOnly]);

  const list = useQuery({
    queryKey: ["memories", params.toString()],
    queryFn: () => api.memories(params),
  });

  const detail = useQuery({
    queryKey: ["memory", selectedId],
    queryFn: () => api.memory(selectedId!),
    enabled: !!selectedId,
  });

  const memoryViolations = useQuery({
    queryKey: ["memory-violations", selectedId],
    queryFn: () => api.getMemoryViolations(selectedId!),
    enabled: !!selectedId,
    retry: false,
  });

  const breakdown = useMemo(() => {
    const prov = detail.data?.provenance ?? [];
    const last = [...prov]
      .reverse()
      .find((e) => e.event_type === "trust_updated");
    const meta = last?.event_metadata as
      | { breakdown?: Record<string, unknown> }
      | undefined;
    return meta?.breakdown;
  }, [detail.data]);

  return (
    <div className="flex gap-6">
      <div className="flex-1 space-y-4 min-w-0">
        <h1 className="text-2xl font-semibold">Memory explorer</h1>

        <Card className="flex flex-wrap gap-4 items-end">
          <label className="text-sm space-y-1">
            <span className="text-zinc-500">Agent ID</span>
            <input
              className="block w-64 rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm"
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              placeholder="uuid"
            />
          </label>
          <label className="text-sm space-y-1">
            <span className="text-zinc-500">Source type</span>
            <input
              className="block w-40 rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm"
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value)}
            />
          </label>
          <label className="text-sm space-y-1 flex-1 min-w-[200px]">
            <span className="text-zinc-500">
              Min trust: {minTrust.toFixed(2)}
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={minTrust}
              onChange={(e) => setMinTrust(Number(e.target.value))}
              className="w-full accent-emerald-500"
            />
          </label>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={flaggedOnly}
              onChange={(e) => setFlaggedOnly(e.target.checked)}
              className="rounded border-zinc-600"
            />
            Flagged only
          </label>
        </Card>

        <div className="overflow-x-auto rounded-xl border border-zinc-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-800 bg-zinc-900/50 text-left text-zinc-400">
                <th className="p-2 font-medium">ID</th>
                <th className="p-2 font-medium">Preview</th>
                <th className="p-2 font-medium">Agent</th>
                <th className="p-2 font-medium">Source</th>
                <th className="p-2 font-medium">Trust</th>
                <th className="p-2 font-medium">Flag</th>
                <th className="p-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {list.data?.items.map((m: MemoryListItem) => (
                <tr
                  key={m.id}
                  onClick={() => selectMemory(m.id)}
                  className={cn(
                    "border-b border-zinc-800/80 cursor-pointer hover:bg-zinc-800/40",
                    selectedId === m.id && "bg-zinc-800/60",
                  )}
                >
                  <td className="p-2 font-mono text-xs text-zinc-500">
                    {m.id.slice(0, 8)}…
                  </td>
                  <td className="p-2 max-w-xs truncate">{preview(m.content)}</td>
                  <td className="p-2">{m.agent_name ?? "—"}</td>
                  <td className="p-2">{m.source_type}</td>
                  <td className="p-2">{trustBadge(m.trust_score)}</td>
                  <td className="p-2">
                    {m.is_flagged ? (
                      <AlertTriangle className="w-4 h-4 text-red-500" />
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="p-2 text-zinc-500 whitespace-nowrap">
                    {new Date(m.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <aside
        className={cn(
          "w-[400px] shrink-0 border-l border-zinc-800 pl-6 space-y-4 max-h-[calc(100vh-8rem)] overflow-y-auto",
          !selectedId && "opacity-50 pointer-events-none",
        )}
      >
        <h2 className="text-lg font-medium">Detail</h2>
        {!selectedId && (
          <p className="text-zinc-500 text-sm">Select a memory row.</p>
        )}
        {selectedId && detail.isLoading && <p className="text-zinc-500">Loading…</p>}
        {detail.data && (
          <>
            <Card>
              <p className="text-xs text-zinc-500 mb-2">Content</p>
              <p className="text-sm whitespace-pre-wrap">{detail.data.content}</p>
            </Card>
            <Card>
              <p className="text-sm font-medium mb-2">Trust breakdown</p>
              {breakdown ? (
                <pre className="text-xs text-zinc-400 overflow-x-auto">
                  {JSON.stringify(breakdown, null, 2)}
                </pre>
              ) : (
                <p className="text-xs text-zinc-500">
                  No engine breakdown yet. Run trust decay to attach factors to
                  provenance.
                </p>
              )}
            </Card>
            <Card>
              <p className="text-sm font-medium mb-2">Provenance</p>
              <ul className="space-y-3 border-l border-zinc-700 pl-3">
                {detail.data.provenance.map((e) => (
                  <li key={e.id} className="text-xs">
                    <p className="text-emerald-400 font-medium">{e.event_type}</p>
                    <p className="text-zinc-500">
                      {new Date(e.timestamp).toLocaleString()}
                    </p>
                    {Object.keys(e.event_metadata).length > 0 && (
                      <pre className="mt-1 text-zinc-500 overflow-x-auto max-h-32">
                        {JSON.stringify(e.event_metadata, null, 2)}
                      </pre>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
            <Card>
              <p className="text-sm font-medium mb-2">Violations</p>
              {memoryViolations.isLoading && (
                <p className="text-xs text-zinc-500">Loading…</p>
              )}
              {memoryViolations.isError && (
                <p className="text-xs text-zinc-500">
                  Violations could not be loaded.
                </p>
              )}
              {!memoryViolations.isLoading &&
                !memoryViolations.isError &&
                (memoryViolations.data?.length ?? 0) === 0 && (
                  <Badge className="bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                    No violations detected
                  </Badge>
                )}
              {!memoryViolations.isLoading &&
                !memoryViolations.isError &&
                (memoryViolations.data?.length ?? 0) > 0 && (
                  <ul className="space-y-2">
                    {(memoryViolations.data ?? []).map((v) => (
                      <li
                        key={v.id}
                        className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-2 text-xs"
                      >
                        <div className="flex items-center gap-2 flex-wrap mb-1">
                          <span className="font-mono text-zinc-300">
                            {v.rule_name}
                          </span>
                          <Badge className={severityBadgeClass(v.severity)}>
                            {v.severity}
                          </Badge>
                        </div>
                        <p className="text-zinc-400">{v.description}</p>
                      </li>
                    ))}
                  </ul>
                )}
            </Card>
            <Button
              variant="outline"
              className="w-full"
              onClick={closeDetail}
            >
              Close
            </Button>
          </>
        )}
      </aside>
    </div>
  );
}
