import { NavLink, Route, Routes } from "react-router-dom";
import { ShieldAlert } from "lucide-react";
import { NotificationBell } from "./components/NotificationBell";
import { DashboardPage } from "./pages/DashboardPage";
import { MemoriesPage } from "./pages/MemoriesPage";
import { GraphPage } from "./pages/GraphPage";
import { AgentsPage } from "./pages/AgentsPage";
import { ViolationsPage } from "./pages/ViolationsPage";
import { RulesPage } from "./pages/RulesPage";
import { AttacksPage } from "./pages/AttacksPage";
import { cn } from "./components/ui";

const nav = [
  { to: "/", label: "Dashboard", icon: null },
  { to: "/memories", label: "Memories", icon: null },
  { to: "/violations", label: "Violations", icon: null },
  { to: "/graph", label: "Graph", icon: null },
  { to: "/agents", label: "Agents", icon: null },
  { to: "/rules", label: "Rules", icon: null },
  { to: "/attacks", label: "Attacks", icon: ShieldAlert },
];

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-zinc-800 bg-zinc-900/90 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto max-w-7xl px-4 py-3 flex items-center gap-8">
          <div className="flex flex-col leading-tight">
            <span className="font-semibold text-emerald-400">Agent Memory</span>
            <span className="text-[10px] text-zinc-500 tracking-wide">AGM</span>
          </div>
          <nav className="flex flex-wrap gap-1 flex-1 min-w-0">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === "/"}
                className={({ isActive }) =>
                  cn(
                    "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors",
                    n.icon
                      ? isActive
                        ? "bg-red-950/40 text-red-300"
                        : "text-red-400 hover:text-red-300"
                      : isActive
                        ? "bg-zinc-800 text-white"
                        : "text-zinc-400 hover:text-zinc-200",
                  )
                }
              >
                {n.icon && <n.icon className="h-3.5 w-3.5" />}
                {n.label}
              </NavLink>
            ))}
          </nav>
          <NotificationBell />
        </div>
      </header>
      <main className="flex-1 mx-auto max-w-7xl w-full px-4 py-6">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/memories" element={<MemoriesPage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/violations" element={<ViolationsPage />} />
          <Route path="/rules" element={<RulesPage />} />
          <Route path="/attacks" element={<AttacksPage />} />
        </Routes>
      </main>
    </div>
  );
}
