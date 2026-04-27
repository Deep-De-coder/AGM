import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  Handle,
  Position,
  type Edge,
  type Node,
  type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import { api } from "../api";
import type { GraphNode } from "../api";
import { Badge, Button, Card, cn } from "../components/ui";
import { Graph3D } from "../components/Graph3D";
import { ProjectIngest } from "../components/ProjectIngest";

// ── 2D React Flow node renderers (unchanged) ──────────────────────────────────

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

const nodeTypes = { memory: MemoryNode, agent: AgentNode, system: SystemNode };

// ── node detail panel ─────────────────────────────────────────────────────────

function NodeDetailPanel({
  node,
  onClose,
}: {
  node: GraphNode;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const sc = node.data.safety_context as Record<string, unknown> | undefined;
  const isMemory = node.kind === "memory" || node.kind === "project_file";
  const trust = node.data.trust_score as number | undefined;
  const state = node.data.memory_state as string | undefined;
  const depth = node.data.causal_depth as number | undefined;
  const filePath = sc?.file_path as string | undefined;
  const content = node.data.content as string | undefined;

  const memoryId = isMemory ? (node.data.memory_id as string | undefined) : undefined;

  function trustBadgeClass(t: number) {
    if (t > 0.7) return "bg-emerald-500/20 text-emerald-300";
    if (t >= 0.4) return "bg-amber-500/20 text-amber-300";
    return "bg-red-500/20 text-red-300";
  }

  return (
    <aside className="w-[340px] shrink-0 border-l border-zinc-800 pl-5 space-y-3 max-h-[calc(100vh-8rem)] overflow-y-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Node detail</h2>
        <button
          type="button"
          className="text-zinc-500 hover:text-zinc-200 text-xs"
          onClick={onClose}
        >
          ✕ close
        </button>
      </div>

      <Card className="space-y-2 text-sm">
        <div>
          <span className="text-zinc-500 text-xs">ID</span>
          <p className="font-mono text-xs truncate text-zinc-300">{node.id}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-zinc-500 text-xs">Type</span>
          <Badge className="bg-zinc-700 text-zinc-200">{node.kind}</Badge>
        </div>
        {trust != null && (
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 text-xs">Trust</span>
            <Badge className={trustBadgeClass(trust)}>{trust.toFixed(3)}</Badge>
          </div>
        )}
        {state && (
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 text-xs">State</span>
            <Badge className="bg-zinc-700 text-zinc-200">{state}</Badge>
          </div>
        )}
        {depth != null && (
          <div>
            <span className="text-zinc-500 text-xs">Causal depth</span>
            <p className="text-zinc-300">{depth}</p>
          </div>
        )}
        {filePath && (
          <div>
            <span className="text-zinc-500 text-xs">File path</span>
            <p className="font-mono text-xs text-cyan-300 truncate">{filePath}</p>
          </div>
        )}
      </Card>

      {content && (
        <Card>
          <p className="text-xs text-zinc-500 mb-1">Content preview</p>
          <p className="text-xs text-zinc-300 whitespace-pre-wrap">
            {content.length > 200 ? content.slice(0, 200) + "…" : content}
          </p>
        </Card>
      )}

      {memoryId && (
        <Button
          variant="outline"
          className="w-full text-xs"
          onClick={() => navigate(`/memories?memory=${memoryId}`)}
        >
          View in Memories →
        </Button>
      )}
    </aside>
  );
}

// ── main page ─────────────────────────────────────────────────────────────────

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function GraphPage() {
  const [mode, setMode] = useState<"2d" | "3d">("2d");
  const [projectName, setProjectName] = useState("");
  const [projectList, setProjectList] = useState<string[]>(() =>
    load("agm_projects", [] as string[]),
  );
  const [showIngest, setShowIngest] = useState(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  const graphQuery = useQuery({
    queryKey: ["graph", mode, projectName],
    queryFn: () => {
      if (projectName || mode === "3d") {
        return api.getGraph3D({
          project_name: projectName || undefined,
          show_3d: mode === "3d",
        });
      }
      return api.graph();
    },
    refetchInterval: 10_000,
  });

  // ── 2D layout ──
  const { nodes2d, edges2d } = useMemo(() => {
    const raw = graphQuery.data;
    if (!raw) return { nodes2d: [] as Node[], edges2d: [] as Edge[] };

    const nodes2d: Node[] = raw.nodes.map((n, i) => {
      const col = i % 6;
      const row = Math.floor(i / 6);
      return {
        id: n.id,
        type: n.kind === "memory" || n.kind === "project_file"
          ? "memory"
          : n.kind === "agent"
          ? "agent"
          : "system",
        position: { x: col * 280, y: row * 140 },
        data: {
          label: n.label,
          ...n.data,
          name: n.data.name as string | undefined,
          content: n.data.content as string | undefined,
          color: n.data.color as string | undefined,
          trust_score: n.data.trust_score as number | undefined,
        },
      };
    });

    const edges2d: Edge[] = raw.edges.map((e) => {
      const et = e.type ?? "provenance";
      const causal = et === "causal";
      const dependsOn = et === "depends_on";
      const stroke = dependsOn ? "#FF5722" : causal ? "#3b82f6" : "#52525b";
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        animated: e.label === "trust_updated",
        style: causal || dependsOn
          ? { stroke, strokeWidth: 2 }
          : { stroke, strokeDasharray: "6 4" },
        labelStyle: { fill: "#a1a1aa", fontSize: 10 },
      };
    });

    return { nodes2d, edges2d };
  }, [graphQuery.data]);

  const onNodeClick2D = useCallback(() => {}, []);

  function handleIngestSuccess(name: string) {
    setProjectList((prev) => {
      const next = [...new Set([...prev, name])];
      localStorage.setItem("agm_projects", JSON.stringify(next));
      return next;
    });
  }

  return (
    <div className="space-y-4 h-[calc(100vh-7rem)] flex flex-col">
      {/* top bar */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Memory graph</h1>

        <div className="flex flex-wrap items-center gap-3">
          {/* project filter */}
          <select
            className="rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm"
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
          >
            <option value="">All memories</option>
            {projectList.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>

          {/* 2D / 3D toggle */}
          <div className="flex rounded-lg border border-zinc-700 overflow-hidden text-sm">
            {(["2d", "3d"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={cn(
                  "px-3 py-1.5 font-medium transition-colors",
                  mode === m
                    ? "bg-zinc-700 text-white"
                    : "bg-zinc-900 text-zinc-400 hover:text-zinc-200",
                )}
              >
                {m.toUpperCase()}
              </button>
            ))}
          </div>

          {/* ingest button */}
          <Button onClick={() => setShowIngest(true)}>Ingest Project</Button>

          {/* legend */}
          <div className="flex flex-wrap items-center gap-4 text-xs text-zinc-400">
            <span>
              <span className="inline-block w-6 h-0.5 bg-blue-500 align-middle mr-1" />
              Causal
            </span>
            <span>
              <span className="inline-block w-6 h-0.5 bg-orange-500 align-middle mr-1" />
              Depends
            </span>
            <span>
              <span className="inline-block w-6 border-t border-dashed border-zinc-500 align-middle mr-1" />
              Provenance
            </span>
            <span className="text-zinc-500">Refreshes every 10s</span>
          </div>
        </div>
      </div>

      {/* graph + detail panel */}
      <div className="flex flex-1 gap-0 min-h-0">
        <div
          className={cn(
            "flex-1 rounded-xl border border-zinc-800 overflow-hidden bg-zinc-900/50 min-h-0",
            selectedNode ? "rounded-r-none border-r-0" : "",
          )}
        >
          {graphQuery.isLoading ? (
            <p className="p-8 text-zinc-500">Loading graph…</p>
          ) : mode === "2d" ? (
            <ReactFlowProvider>
              <ReactFlow
                nodes={nodes2d}
                edges={edges2d}
                nodeTypes={nodeTypes}
                fitView
                onNodeClick={onNodeClick2D}
                proOptions={{ hideAttribution: true }}
              >
                <MiniMap />
                <Controls />
                <Background gap={16} color="#27272a" />
              </ReactFlow>
            </ReactFlowProvider>
          ) : (
            <Graph3D
              nodes={graphQuery.data?.nodes ?? []}
              edges={graphQuery.data?.edges ?? []}
              selectedNodeId={selectedNode?.id ?? null}
              onNodeClick={(n) => setSelectedNode((prev) => (prev?.id === n.id ? null : n))}
            />
          )}
        </div>

        {selectedNode && (
          <NodeDetailPanel node={selectedNode} onClose={() => setSelectedNode(null)} />
        )}
      </div>

      {showIngest && (
        <ProjectIngest
          onClose={() => setShowIngest(false)}
          onSuccess={handleIngestSuccess}
        />
      )}
    </div>
  );
}
