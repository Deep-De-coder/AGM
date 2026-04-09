import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Card } from "../components/ui";

export function AgentsPage() {
  const q = useQuery({
    queryKey: ["agents"],
    queryFn: api.agents,
    refetchInterval: 30_000,
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
            </tr>
          </thead>
          <tbody>
            {q.data?.map((a) => (
              <tr key={a.id} className="border-b border-zinc-800/80">
                <td className="p-3 font-medium">{a.name}</td>
                <td className="p-3 tabular-nums">{a.memory_count}</td>
                <td className="p-3 tabular-nums">{a.avg_trust_score.toFixed(4)}</td>
                <td className="p-3 text-red-400 tabular-nums">
                  {a.flagged_memory_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {q.data?.length === 0 && (
        <Card>
          <p className="text-zinc-500">No agents registered yet.</p>
        </Card>
      )}
    </div>
  );
}
