export type ViolationSeverity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";

export function severityBadgeClass(s: string): string {
  switch (s) {
    case "CRITICAL":
      return "bg-red-500/20 text-red-300 border border-red-500/40";
    case "HIGH":
      return "bg-orange-500/20 text-orange-300 border border-orange-500/40";
    case "MEDIUM":
      return "bg-yellow-500/20 text-yellow-300 border border-yellow-500/40";
    case "LOW":
      return "bg-blue-500/20 text-blue-300 border border-blue-500/40";
    default:
      return "bg-zinc-500/20 text-zinc-300 border border-zinc-600";
  }
}
