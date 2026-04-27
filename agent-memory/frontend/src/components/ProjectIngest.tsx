import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api } from "../api";
import type { IngestResponse, LearnResponse } from "../api";
import { Badge, Button, Card, cn } from "./ui";

const EXT_OPTIONS = [".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".yaml", ".json", ".go", ".rs"];
const DEFAULT_EXTS = [".py", ".ts", ".tsx", ".js", ".md"];

interface Props {
  onClose: () => void;
  onSuccess: (projectName: string) => void;
}

export function ProjectIngest({ onClose, onSuccess }: Props) {
  const [projectName, setProjectName] = useState("");
  const [projectPath, setProjectPath] = useState("");
  const [agentId, setAgentId] = useState("");
  const [extensions, setExtensions] = useState<string[]>(DEFAULT_EXTS);

  type Phase = "form" | "ingesting" | "result" | "learning" | "learned";
  const [phase, setPhase] = useState<Phase>("form");
  const [error, setError] = useState("");
  const [result, setResult] = useState<IngestResponse | null>(null);
  const [learnResult, setLearnResult] = useState<LearnResponse | null>(null);
  const [learnAgentId, setLearnAgentId] = useState("");
  const [learnError, setLearnError] = useState("");

  const agentsQ = useQuery({ queryKey: ["agents"], queryFn: api.agents });

  function toggleExt(ext: string) {
    setExtensions((prev) =>
      prev.includes(ext) ? prev.filter((e) => e !== ext) : [...prev, ext],
    );
  }

  async function handleIngest() {
    if (!projectName.trim() || !projectPath.trim() || !agentId) {
      setError("Project name, path, and agent are required.");
      return;
    }
    setError("");
    setPhase("ingesting");
    try {
      const r = await api.ingestProject({
        project_name: projectName.trim(),
        project_path: projectPath.trim(),
        agent_id: agentId,
        file_extensions: extensions,
      });
      setResult(r);
      setPhase("result");
      onSuccess(r.project_name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingest failed");
      setPhase("form");
    }
  }

  async function handleLearn() {
    if (!result || !learnAgentId) return;
    setLearnError("");
    setPhase("learning");
    try {
      const lr = await api.learnProject(result.project_name, learnAgentId);
      setLearnResult(lr);
      setPhase("learned");
    } catch (err) {
      setLearnError(err instanceof Error ? err.message : "Learn failed");
      setPhase("result");
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-lg rounded-2xl border border-zinc-700 bg-zinc-900 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className="absolute right-4 top-4 text-zinc-500 hover:text-zinc-200"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </button>

        <h2 className="mb-4 text-lg font-semibold">Ingest Project</h2>

        {phase === "form" || phase === "ingesting" ? (
          <div className="space-y-4">
            <label className="block text-sm space-y-1">
              <span className="text-zinc-400">Project name</span>
              <input
                className="block w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="my-project"
                disabled={phase === "ingesting"}
              />
            </label>

            <label className="block text-sm space-y-1">
              <span className="text-zinc-400">Project path (absolute on server)</span>
              <input
                className="block w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm font-mono"
                value={projectPath}
                onChange={(e) => setProjectPath(e.target.value)}
                placeholder="/home/user/my-project"
                disabled={phase === "ingesting"}
              />
            </label>

            <label className="block text-sm space-y-1">
              <span className="text-zinc-400">Agent</span>
              <select
                className="block w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                disabled={phase === "ingesting"}
              >
                <option value="">— select agent —</option>
                {(agentsQ.data ?? []).map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>

            <div className="space-y-1 text-sm">
              <span className="text-zinc-400">File extensions</span>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {EXT_OPTIONS.map((ext) => (
                  <button
                    key={ext}
                    type="button"
                    onClick={() => toggleExt(ext)}
                    disabled={phase === "ingesting"}
                    className={cn(
                      "rounded px-2 py-0.5 text-xs font-mono border transition-colors disabled:opacity-50",
                      extensions.includes(ext)
                        ? "bg-emerald-700 border-emerald-600 text-white"
                        : "bg-zinc-800 border-zinc-700 text-zinc-400 hover:border-zinc-500",
                    )}
                  >
                    {ext}
                  </button>
                ))}
              </div>
            </div>

            {error && <p className="text-xs text-red-400">{error}</p>}

            <Button
              className="w-full"
              onClick={() => void handleIngest()}
              disabled={phase === "ingesting"}
            >
              {phase === "ingesting" ? "Ingesting…" : "Ingest Project"}
            </Button>
          </div>
        ) : phase === "result" && result ? (
          <div className="space-y-4">
            <Card className="space-y-2">
              <p className="text-sm font-medium text-emerald-400">✓ Ingest complete</p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                <span className="text-zinc-500">Files ingested</span>
                <span className="font-mono">{result.files_ingested}</span>
                <span className="text-zinc-500">Dependency edges</span>
                <span className="font-mono">{result.edges_created}</span>
                <span className="text-zinc-500">Root memory ID</span>
                <span className="font-mono text-xs truncate">{result.root_memory_id.slice(0, 16)}…</span>
              </div>
            </Card>

            <div className="space-y-2">
              <p className="text-sm text-zinc-400">Teach an agent this project:</p>
              <div className="flex gap-2">
                <select
                  className="flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
                  value={learnAgentId}
                  onChange={(e) => setLearnAgentId(e.target.value)}
                >
                  <option value="">— select agent —</option>
                  {(agentsQ.data ?? []).map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
                <Button onClick={() => void handleLearn()} disabled={!learnAgentId}>
                  Learn
                </Button>
              </div>
              {learnError && <p className="text-xs text-red-400">{learnError}</p>}
            </div>
          </div>
        ) : phase === "learning" ? (
          <p className="text-zinc-400 text-sm">Building project understanding…</p>
        ) : phase === "learned" && learnResult ? (
          <div className="space-y-3">
            <Card>
              <p className="text-sm font-medium text-emerald-400 mb-2">✓ Agent learned the project</p>
              <div className="text-sm space-y-1">
                <p className="text-zinc-500">
                  Synthesis memory:{" "}
                  <span className="font-mono text-zinc-300">
                    {learnResult.synthesis_memory_id.slice(0, 16)}…
                  </span>
                </p>
                <p className="text-zinc-500">Files learned: {learnResult.files_learned}</p>
              </div>
            </Card>
            {learnResult.core_files.length > 0 && (
              <Card>
                <p className="text-xs text-zinc-500 mb-1">Core files</p>
                <ul className="space-y-0.5">
                  {learnResult.core_files.slice(0, 8).map((f) => (
                    <li key={f} className="text-xs font-mono text-zinc-300 truncate">
                      {f}
                    </li>
                  ))}
                </ul>
              </Card>
            )}
            {learnResult.entry_points.length > 0 && (
              <Card>
                <p className="text-xs text-zinc-500 mb-1">Entry points</p>
                <div className="flex flex-wrap gap-1">
                  {learnResult.entry_points.slice(0, 5).map((ep) => (
                    <Badge key={ep} className="bg-sky-500/20 text-sky-300 font-mono text-xs">
                      {ep}
                    </Badge>
                  ))}
                </div>
              </Card>
            )}
            <Button variant="outline" className="w-full" onClick={onClose}>
              Close
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
