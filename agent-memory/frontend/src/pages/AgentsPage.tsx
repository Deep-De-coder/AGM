import { useQueries, useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { AgentDetailPanel } from "../components/AgentDetailPanel";
import { Badge, Card } from "../components/ui";
import { cn } from "../components/ui";

function dcaBadge(ctx: string | undefined) {
  const c = ctx ?? "SAFE";
  if (c === "SAFE")
    return <Badge className="bg-emerald-500/20 text-emerald-300">SAFE</Badge>;
  if (c === "SEMI_MATURE")
    return <Badge className="bg-amber-500/20 text-amber-300">SEMI</Badge>;
  return (
    <Badge className="animate-pulse bg-red-600/30 text-red-200 border border-red-500/50">
      DANGER
    </Badge>
  );
}

function quorumBadge(status: string | undefined) {
  const s = status ?? "FULL_QUORUM";
  if (s === "FULL_QUORUM")
    return <Badge className="bg-emerald-500/20 text-emerald-300">Full</Badge>;
  if (s === "PARTIAL_QUORUM")
    return <Badge className="bg-amber-500/20 text-amber-300">Partial</Badge>;
  return <Badge className="bg-red-500/20 text-red-300">Failed</Badge>;
}

export function AgentsPage() {
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [selectedAgentName, setSelectedAgentName] = useState<string>("");
  const [panelOpen, setPanelOpen] = useState(false);

  const q = useQuery({
    queryKey: ["agents"],
    queryFn: api.agents,
    refetchInterval: 30_000,
  });

  const agents = q.data ?? [];
  const dcaQueries = useQueries({
    queries: agents.map((a) => ({
      queryKey: ["stats-dca", a.id],
      queryFn: () => api.statsDca(a.id),
      refetchInterval: 60_000,
      staleTime: 30_000,
    })),
  });
  const quorumQueries = useQueries({
    queries: agents.map((a) => ({
      queryKey: ["agent-quorum", a.id],
      queryFn: () => api.agentQuorum(a.id),
      refetchInterval: 60_000,
      staleTime: 30_000,
    })),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Agent registry</h1>
      <div className="overflow-x-auto rounded-xl border border-zinc-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 bg-zinc-900/50 text-left text-zinc-400">
              <th className="p-3 font-medium">Name</th>
              <th className="p-3 font-medium">Memories</th>
              <th className="p-3 font-medium">Avg trust</th>
              <th className="p-3 font-medium">Flagged</th>
              <th className="p-3 font-medium">DCA</th>
              <th className="p-3 font-medium">Quorum</th>
              <th className="p-3 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a, i) => (
              <tr
                key={a.id}
                onClick={() => {
                  setSelectedAgentId(a.id);
                  setSelectedAgentName(a.name);
                  setPanelOpen(true);
                }}
                className={cn(
                  "border-b border-zinc-800/80 cursor-pointer hover:bg-zinc-800/40",
                  selectedAgentId === a.id && "bg-zinc-800/60",
                )}
              >
                <td className="p-3 font-medium">{a.name}</td>
                <td className="p-3 tabular-nums">{a.memory_count}</td>
                <td className="p-3 tabular-nums">{a.avg_trust_score.toFixed(4)}</td>
                <td className="p-3 text-red-400 tabular-nums">
                  {a.flagged_memory_count}
                </td>
                <td className="p-3">
                  {dcaQueries[i]?.isLoading ? (
                    <span className="text-zinc-500">…</span>
                  ) : dcaQueries[i]?.isError ? (
                    <span className="text-zinc-600">—</span>
                  ) : (
                    dcaBadge(dcaQueries[i]?.data?.net_context)
                  )}
                </td>
                <td className="p-3">
                  {quorumQueries[i]?.isLoading ? (
                    <span className="text-zinc-500">…</span>
                  ) : quorumQueries[i]?.isError ? (
                    <span className="text-zinc-600">—</span>
                  ) : (
                    quorumBadge(quorumQueries[i]?.data?.quorum_status)
                  )}
                </td>
                <td className="p-3 text-zinc-500">
                  <ChevronRight className="h-4 w-4" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {agents.length === 0 && (
        <Card>
          <p className="text-zinc-500">No agents registered yet.</p>
        </Card>
      )}
      {panelOpen && selectedAgentId && (
        <AgentDetailPanel
          agentId={selectedAgentId}
          agentName={selectedAgentName}
          onClose={() => setPanelOpen(false)}
        />
      )}
    </div>
  );
}
