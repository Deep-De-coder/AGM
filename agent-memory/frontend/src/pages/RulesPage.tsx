import { Badge, Card } from "../components/ui";
import type { ViolationSeverity } from "../lib/severity";
import { severityBadgeClass } from "../lib/severity";

type RuleRow = {
  id: string;
  name: string;
  severity: ViolationSeverity;
  description: string;
  detects: string;
};

const RULES: RuleRow[] = [
  {
    id: "R-001",
    name: "write_rate_flood",
    severity: "HIGH",
    description:
      "Flags memories when the originating session exceeds a safe write volume.",
    detects:
      "Session write count to Redis exceeds 50 writes in the rolling window (trust engine).",
  },
  {
    id: "R-002",
    name: "source_inconsistency",
    severity: "HIGH",
    description:
      "Detects contradictions between negated claims in a memory and peer content.",
    detects:
      "Negated terms from the memory appear positively in three or more high-trust, non-flagged peers in the same agent/session group.",
  },
  {
    id: "R-003",
    name: "trust_chain_contamination",
    severity: "MEDIUM",
    description:
      "Penalizes reading too many already-flagged memories within one session.",
    detects:
      "Flagged-memory read counter for the agent/session is three or more.",
  },
  {
    id: "R-004",
    name: "rapid_modification",
    severity: "MEDIUM",
    description:
      "Detects bursty provenance activity that may indicate abuse or loops.",
    detects:
      "More than five provenance events within any ten-minute window for the memory.",
  },
  {
    id: "R-005",
    name: "pii_and_secret_leak",
    severity: "CRITICAL",
    description:
      "Scans content for patterns that resemble credentials, tokens, or regulated PII.",
    detects:
      "Structured patterns such as API keys, JWT-like blobs, or high-confidence PII regex matches.",
  },
  {
    id: "R-006",
    name: "prompt_injection_signature",
    severity: "HIGH",
    description:
      "Matches known override phrases used to manipulate tool or system behavior.",
    detects:
      "Substrings aligned with an injection dictionary (e.g. “ignore previous”, “system:”, “</instruction>”).",
  },
  {
    id: "R-007",
    name: "cross_session_reference",
    severity: "MEDIUM",
    description:
      "Finds references to other sessions or tenants that should stay isolated.",
    detects:
      "UUIDs or session labels in content that do not match the memory’s session scope.",
  },
  {
    id: "R-008",
    name: "stale_high_trust",
    severity: "LOW",
    description:
      "Down-weights very old memories that still carry high trust without refresh.",
    detects:
      "Age and trust_score combination crosses a staleness threshold from decay snapshots.",
  },
  {
    id: "R-009",
    name: "embedding_outlier",
    severity: "MEDIUM",
    description:
      "Compares vector embeddings to the corpus to find semantic outliers.",
    detects:
      "Cosine distance to k-nearest neighbors exceeds a configured cutoff.",
  },
  {
    id: "R-010",
    name: "metadata_source_mismatch",
    severity: "LOW",
    description:
      "Validates that declared source metadata matches observed provenance.",
    detects:
      "source_type or source_identifier inconsistent with ingestion logs or tool receipts.",
  },
];

export function RulesPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Rules reference</h1>
      <p className="text-sm text-zinc-400 max-w-3xl">
        Built-in policy rules evaluated against memories and sessions. Severities
        are used for violation records and notifications.
      </p>

      <Card className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 bg-zinc-900/50 text-left text-zinc-400">
              <th className="p-3 font-medium whitespace-nowrap">Rule ID</th>
              <th className="p-3 font-medium">Name</th>
              <th className="p-3 font-medium">Severity</th>
              <th className="p-3 font-medium min-w-[200px]">Description</th>
              <th className="p-3 font-medium min-w-[220px]">What it detects</th>
            </tr>
          </thead>
          <tbody>
            {RULES.map((r) => (
              <tr
                key={r.id}
                className="border-b border-zinc-800/80 hover:bg-zinc-800/30"
              >
                <td className="p-3 font-mono text-xs text-zinc-500 whitespace-nowrap">
                  {r.id}
                </td>
                <td className="p-3 font-mono text-xs">{r.name}</td>
                <td className="p-3">
                  <Badge className={severityBadgeClass(r.severity)}>
                    {r.severity}
                  </Badge>
                </td>
                <td className="p-3 text-zinc-300">{r.description}</td>
                <td className="p-3 text-zinc-400">{r.detects}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <p className="text-sm text-zinc-500">
        To add custom rules, see{" "}
        <code className="text-emerald-400/90">backend/rules/README.md</code>.
      </p>
    </div>
  );
}
