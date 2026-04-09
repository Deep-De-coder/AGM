import { NavLink, Route, Routes } from "react-router-dom";
import { NotificationBell } from "./components/NotificationBell";
import { DashboardPage } from "./pages/DashboardPage";
import { MemoriesPage } from "./pages/MemoriesPage";
import { GraphPage } from "./pages/GraphPage";
import { AgentsPage } from "./pages/AgentsPage";
import { ViolationsPage } from "./pages/ViolationsPage";
import { RulesPage } from "./pages/RulesPage";
import { cn } from "./components/ui";

const nav = [
  { to: "/", label: "Dashboard" },
  { to: "/memories", label: "Memories" },
  { to: "/violations", label: "Violations" },
  { to: "/graph", label: "Graph" },
  { to: "/agents", label: "Agents" },
  { to: "/rules", label: "Rules" },
];

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-zinc-800 bg-zinc-900/90 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto max-w-7xl px-4 py-3 flex items-center gap-8">
          <span className="font-semibold text-emerald-400">Agent Memory</span>
          <nav className="flex flex-wrap gap-1 flex-1 min-w-0">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === "/"}
                className={({ isActive }) =>
                  cn(
                    "rounded-lg px-3 py-1.5 text-sm transition-colors",
                    isActive
                      ? "bg-zinc-800 text-white"
                      : "text-zinc-400 hover:text-zinc-200",
                  )
                }
              >
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
        </Routes>
      </main>
    </div>
  );
}
