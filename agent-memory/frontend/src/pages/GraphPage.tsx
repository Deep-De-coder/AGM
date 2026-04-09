import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeProps,
  Handle,
  Position,
} from "reactflow";
import "reactflow/dist/style.css";
import { api } from "../api";

function MemoryNode({ data }: NodeProps) {
  const d = data as {
    label?: string;
    content?: string;
    color?: string;
    trust_score?: number;
  };
  return (
    <div
      className="rounded-lg border-2 px-3 py-2 max-w-[220px] text-xs shadow-lg bg-zinc-900"
      style={{ borderColor: d.color ?? "#64748b" }}
      title={d.content ?? d.label}
    >
      <Handle type="target" position={Position.Left} />
      <p className="font-medium text-zinc-200 truncate">{d.label}</p>
      {d.trust_score != null && (
        <p className="text-zinc-500 mt-1">trust {d.trust_score.toFixed(3)}</p>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function AgentNode({ data }: NodeProps) {
  const d = data as { name?: string; label?: string };
  return (
    <div className="rounded-full border border-sky-500/50 bg-sky-950/80 px-4 py-2 text-sm text-sky-200">
      <Handle type="target" position={Position.Left} />
      {d.name ?? d.label}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function SystemNode({ data }: NodeProps) {
  const d = data as { label?: string };
  return (
    <div className="rounded-md border border-violet-500/40 bg-violet-950/60 px-3 py-2 text-xs text-violet-200">
      <Handle type="target" position={Position.Left} />
      {d.label}
    </div>
  );
}

const nodeTypes = {
  memory: MemoryNode,
  agent: AgentNode,
  system: SystemNode,
};

function GraphInner() {
  const q = useQuery({
    queryKey: ["graph"],
    queryFn: api.graph,
    refetchInterval: 10_000,
  });

  const { nodes, edges } = useMemo(() => {
    const raw = q.data;
    if (!raw) return { nodes: [] as Node[], edges: [] as Edge[] };

    const pos = new Map<string, { x: number; y: number }>();
    raw.nodes.forEach((n, i) => {
      const col = i % 6;
      const row = Math.floor(i / 6);
      pos.set(n.id, { x: col * 280, y: row * 140 });
    });

    const nodes: Node[] = raw.nodes.map((n) => ({
      id: n.id,
      type: n.kind === "memory" ? "memory" : n.kind === "agent" ? "agent" : "system",
      position: pos.get(n.id) ?? { x: 0, y: 0 },
      data: {
        label: n.label,
        ...n.data,
        name: n.data.name as string | undefined,
        content: n.data.content as string | undefined,
        color: n.data.color as string | undefined,
        trust_score: n.data.trust_score as number | undefined,
      },
    }));

    const edges: Edge[] = raw.edges.map((e) => {
      const et =
        (e.type as string | undefined) ??
        (e.data?.kind === "causal" ? "causal" : "provenance");
      const causal = et === "causal";
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        animated: e.label === "trust_updated",
        style: causal
          ? { stroke: "#3b82f6", strokeWidth: 2 }
          : { stroke: "#52525b", strokeDasharray: "6 4" },
        labelStyle: { fill: "#a1a1aa", fontSize: 10 },
      };
    });

    return { nodes, edges };
  }, [q.data]);

  const onNodeClick = useCallback(() => {}, []);

  return (
    <div className="space-y-4 h-[calc(100vh-7rem)] flex flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Memory graph</h1>
        <div className="flex flex-wrap items-center gap-4 text-xs text-zinc-400">
          <span>
            <span className="inline-block w-6 h-0.5 bg-blue-500 align-middle mr-1" />{" "}
            Causal
          </span>
          <span>
            <span className="inline-block w-6 border-t border-dashed border-zinc-500 align-middle mr-1" />{" "}
            Provenance
          </span>
          <span className="text-zinc-500">Refreshes every 10s</span>
        </div>
      </div>
      <div className="flex-1 rounded-xl border border-zinc-800 overflow-hidden bg-zinc-900/50">
        {q.isLoading ? (
          <p className="p-8 text-zinc-500">Loading graph…</p>
        ) : (
          <ReactFlowProvider>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              onNodeClick={onNodeClick}
              proOptions={{ hideAttribution: true }}
            >
              <MiniMap />
              <Controls />
              <Background gap={16} color="#27272a" />
            </ReactFlow>
          </ReactFlowProvider>
        )}
      </div>
    </div>
  );
}

export function GraphPage() {
  return <GraphInner />;
}
