import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type NotificationItem } from "../api";
import { Badge, cn } from "./ui";
import { severityBadgeClass } from "../lib/severity";
import { formatTimeAgo } from "../lib/timeAgo";

const POLL_MS = 10_000;

export function NotificationBell() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const unread = useQuery({
    queryKey: ["notifications", "unread-count"],
    queryFn: api.getUnreadCount,
    refetchInterval: POLL_MS,
  });

  const notifications = useQuery({
    queryKey: ["notifications", "list"],
    queryFn: api.getNotifications,
    enabled: open,
    refetchInterval: open ? POLL_MS : false,
  });

  const markRead = useMutation({
    mutationFn: api.markNotificationRead,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const list: NotificationItem[] = (notifications.data ?? []).slice(0, 20);

  function isUnread(n: NotificationItem) {
    const readFlag = (n as NotificationItem & { is_read?: boolean }).is_read;
    if (readFlag === true) return false;
    if (readFlag === false) return true;
    return !n.read_at;
  }

  async function onRowClick(n: NotificationItem) {
    if (!isUnread(n)) return;
    try {
      await markRead.mutateAsync(n.id);
    } catch {
      /* surface via react-query */
    }
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="relative rounded-lg p-2 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100 transition-colors"
        aria-label="Notifications"
      >
        <Bell className="w-5 h-5" />
        {(unread.data ?? 0) > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[1.125rem] h-[1.125rem] px-1 rounded-full bg-red-600 text-white text-[10px] font-semibold flex items-center justify-center tabular-nums">
            {(unread.data ?? 0) > 99 ? "99+" : unread.data}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-[min(100vw-2rem,22rem)] rounded-xl border border-zinc-800 bg-zinc-900 shadow-xl z-50 overflow-hidden">
          <div className="px-3 py-2 border-b border-zinc-800 text-sm font-medium text-zinc-300">
            Notifications
          </div>
          <div className="max-h-[min(70vh,24rem)] overflow-y-auto">
            {notifications.isLoading && (
              <p className="p-4 text-sm text-zinc-500">Loading…</p>
            )}
            {notifications.isError && (
              <p className="p-4 text-sm text-red-400">
                Could not load notifications.
              </p>
            )}
            {!notifications.isLoading &&
              !notifications.isError &&
              list.length === 0 && (
                <p className="p-4 text-sm text-zinc-500">No notifications.</p>
              )}
            {list.map((n) => (
              <button
                key={n.id}
                type="button"
                onClick={() => onRowClick(n)}
                className={cn(
                  "w-full text-left px-3 py-2.5 border-b border-zinc-800/80 hover:bg-zinc-800/50 transition-colors",
                  !isUnread(n) && "opacity-60",
                )}
              >
                <div className="flex items-start gap-2">
                  <Badge
                    className={cn(
                      "shrink-0 mt-0.5",
                      severityBadgeClass(n.severity),
                    )}
                  >
                    {n.severity}
                  </Badge>
                  <div className="min-w-0 flex-1 space-y-1">
                    <p className="text-sm font-medium text-zinc-100 truncate">
                      {n.title}
                    </p>
                    <p className="text-xs text-zinc-400 line-clamp-3">
                      {n.message}
                    </p>
                    <div className="flex items-center gap-2 text-xs text-zinc-500">
                      <span>{formatTimeAgo(n.created_at)}</span>
                      <Link
                        to={`/memories?memory=${encodeURIComponent(n.memory_id)}`}
                        className="text-emerald-400 hover:underline font-mono truncate"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {n.memory_id.slice(0, 8)}…
                      </Link>
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
