import { useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Html, Line, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import {
  forceCenter,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceZ,
} from "d3-force-3d";
import type { GraphEdge, GraphNode } from "../api";

// ── internal types ─────────────────────────────────────────────────────────────

type Pos3 = [number, number, number];

interface SimNode {
  id: string;
  x: number;
  y: number;
  z: number;
  vx?: number;
  vy?: number;
  vz?: number;
  causal_depth: number;
}

interface SimLink {
  source: string;
  target: string;
}

// ── helpers ────────────────────────────────────────────────────────────────────

function nodeConfig(node: GraphNode): { radius: number; color: string; isBox: boolean } {
  switch (node.kind) {
    case "system":
      return { radius: 1.5, color: "#FFD700", isBox: false };
    case "agent":
      return { radius: 1.2, color: "#00BCD4", isBox: false };
    case "project_file":
      return { radius: 0.9, color: "#00E5FF", isBox: true };
    default: {
      const trust = (node.data.trust_score as number | undefined) ?? 1;
      const color = trust > 0.7 ? "#4CAF50" : trust >= 0.4 ? "#FF9800" : "#F44336";
      return { radius: 0.8, color, isBox: false };
    }
  }
}

function edgeConfig(edge: GraphEdge): { color: string; lineWidth: number; dashed: boolean } {
  switch (edge.type) {
    case "depends_on":
      return { color: "#FF5722", lineWidth: 1, dashed: false };
    case "causal":
      return { color: "#2196F3", lineWidth: 1.5, dashed: false };
    default:
      return {
        color: edge.label === "trust_updated" ? "#FF9800" : "#555555",
        lineWidth: 0.5,
        dashed: true,
      };
  }
}

// ── scene sub-components (must live inside Canvas) ─────────────────────────────

function NodeLabel({ pos, label }: { pos: Pos3; label: string }) {
  const [visible, setVisible] = useState(false);
  const prevRef = useRef(false);
  const vecPos = useMemo(
    () => new THREE.Vector3(pos[0], pos[1], pos[2]),
    // eslint intentionally omitted — pos is a stable reference from useMemo
    [pos],
  );

  useFrame(({ camera }) => {
    const shouldShow = camera.position.distanceTo(vecPos) < 50;
    if (shouldShow !== prevRef.current) {
      prevRef.current = shouldShow;
      setVisible(shouldShow);
    }
  });

  if (!visible) return null;
  return (
    <Html position={pos} center style={{ pointerEvents: "none" }}>
      <span
        style={{
          color: "white",
          fontSize: "10px",
          whiteSpace: "nowrap",
          textShadow: "1px 1px 3px black",
          userSelect: "none",
        }}
      >
        {label.length > 28 ? label.slice(0, 28) + "…" : label}
      </span>
    </Html>
  );
}

interface NodeMeshProps {
  node: GraphNode;
  pos: Pos3;
  isSelected: boolean;
  onNodeClick: (node: GraphNode) => void;
}

function NodeMesh({ node, pos, isSelected, onNodeClick }: NodeMeshProps) {
  const { radius, color, isBox } = nodeConfig(node);
  const [hovered, setHovered] = useState(false);

  return (
    <mesh
      position={pos}
      onClick={(e) => {
        e.stopPropagation();
        onNodeClick(node);
      }}
      onPointerOver={(e) => {
        e.stopPropagation();
        setHovered(true);
      }}
      onPointerOut={() => setHovered(false)}
    >
      {isBox ? (
        <boxGeometry args={[radius * 2, radius * 2, radius * 2]} />
      ) : (
        <sphereGeometry args={[radius, 16, 16]} />
      )}
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={isSelected ? 0.5 : hovered ? 0.2 : 0}
      />
      <NodeLabel pos={pos} label={node.label} />
    </mesh>
  );
}

function EdgeLine({ edge, posMap }: { edge: GraphEdge; posMap: Map<string, Pos3> }) {
  const src = posMap.get(edge.source);
  const tgt = posMap.get(edge.target);
  if (!src || !tgt) return null;

  const { color, lineWidth, dashed } = edgeConfig(edge);
  return (
    <Line
      points={[src, tgt]}
      color={color}
      lineWidth={lineWidth}
      dashed={dashed}
      dashScale={dashed ? 2 : 1}
      dashSize={dashed ? 0.5 : 1}
      gapSize={dashed ? 0.5 : 0}
    />
  );
}

interface SceneContentProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  posMap: Map<string, Pos3>;
  selectedNodeId: string | null;
  onNodeClick: (node: GraphNode) => void;
}

function SceneContent({ nodes, edges, posMap, selectedNodeId, onNodeClick }: SceneContentProps) {
  return (
    <>
      {edges.map((e) => (
        <EdgeLine key={e.id} edge={e} posMap={posMap} />
      ))}
      {nodes.map((n) => {
        const pos = posMap.get(n.id);
        if (!pos) return null;
        return (
          <NodeMesh
            key={n.id}
            node={n}
            pos={pos}
            isSelected={selectedNodeId === n.id}
            onNodeClick={onNodeClick}
          />
        );
      })}
    </>
  );
}

// ── public component ───────────────────────────────────────────────────────────

interface Graph3DProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedNodeId: string | null;
  onNodeClick: (node: GraphNode) => void;
}

export function Graph3D({ nodes, edges, selectedNodeId, onNodeClick }: Graph3DProps) {
  const posMap = useMemo((): Map<string, Pos3> => {
    const count = Math.max(nodes.length, 1);
    const simNodes: SimNode[] = nodes.map((n, i) => {
      const hint = n.data.position_hint as { x: number; y: number; z: number } | undefined;
      const angle = (i / count) * 2 * Math.PI;
      const spread = 40;
      return {
        id: n.id,
        x: hint?.x ?? spread * Math.cos(angle),
        y: hint?.y ?? spread * Math.sin(angle),
        z: hint?.z ?? ((n.data.causal_depth as number | undefined) ?? 0) * 10,
        causal_depth: (n.data.causal_depth as number | undefined) ?? 0,
      };
    });

    const nodeIds = new Set(simNodes.map((n) => n.id));
    const simLinks: SimLink[] = edges
      .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
      .map((e) => ({ source: e.source, target: e.target }));

    try {
      const linkForce = forceLink<SimNode, SimLink>(simLinks)
        .id((d) => d.id)
        .distance(20);
      const chargeForce = forceManyBody<SimNode>().strength(-50);
      const centerForce = forceCenter<SimNode>(0, 0, 0);
      const zForce = forceZ<SimNode>((d) => d.causal_depth * 10).strength(0.3);

      forceSimulation<SimNode>(simNodes)
        .numDimensions(3)
        .force("link", linkForce)
        .force("charge", chargeForce)
        .force("center", centerForce)
        .force("z", zForce)
        .stop()
        .tick(300);
    } catch {
      // use initial positions on simulation failure
    }

    return new Map(simNodes.map((n) => [n.id, [n.x, n.y, n.z] as Pos3]));
  }, [nodes, edges]);

  return (
    <div style={{ width: "100%", height: "100%", background: "#000000" }}>
      <Canvas camera={{ position: [0, 0, 80], fov: 60 }}>
        <ambientLight intensity={0.4} />
        <pointLight position={[10, 10, 10]} intensity={1.0} />
        <pointLight position={[-10, -10, -10]} intensity={0.5} />
        <OrbitControls enableDamping dampingFactor={0.05} makeDefault />
        <SceneContent
          nodes={nodes}
          edges={edges}
          posMap={posMap}
          selectedNodeId={selectedNodeId}
          onNodeClick={onNodeClick}
        />
      </Canvas>
    </div>
  );
}
