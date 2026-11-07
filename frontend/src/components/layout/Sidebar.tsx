import { FileAudio, GraduationCap, LogOut } from "lucide-react";
import { NavLink, useNavigate } from "react-router-dom";

import { useLectures, useLogout, useMe } from "@/api/hooks";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { mainNav } from "./nav";

const RECENT_COUNT = 5;

/** Sidebar contents; rendered fixed on desktop and inside a drawer on mobile. */
export function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const navigate = useNavigate();
  const me = useMe();
  const lectures = useLectures();
  const logout = useLogout();

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
      isActive
        ? "bg-sidebar-accent text-sidebar-accent-foreground"
        : "hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
    );

  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="flex h-16 items-center gap-2 px-6">
        <div className="flex size-8 items-center justify-center rounded-lg bg-sidebar-primary text-white">
          <GraduationCap className="size-5" />
        </div>
        <span className="text-base font-semibold text-white">AI Study Buddy</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        <nav aria-label="Main" className="space-y-1 px-3 py-4">
          {mainNav.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"} onClick={onNavigate} className={linkClass}>
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="px-3 pb-4">
          <p className="px-3 pb-2 text-xs font-medium uppercase tracking-wide text-sidebar-foreground/60">
            Recent lectures
          </p>
          {lectures.isPending ? (
            <div className="space-y-2 px-3">
              <Skeleton className="h-4 w-full bg-sidebar-accent" />
              <Skeleton className="h-4 w-3/4 bg-sidebar-accent" />
            </div>
          ) : lectures.data?.length ? (
            <ul aria-label="Recent lectures" className="space-y-0.5">
              {lectures.data.slice(0, RECENT_COUNT).map((l) => (
                <li key={l.id}>
                  <NavLink to={`/lectures/${l.id}`} onClick={onNavigate} className={linkClass} title={l.title}>
                    <FileAudio className="size-4 shrink-0" />
                    <span className="truncate">{l.title}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-3 text-xs text-sidebar-foreground/60">
              {lectures.isError ? "Couldn't load lectures." : "No lectures yet."}
            </p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2 border-t border-sidebar-border px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm text-white">{me.data?.full_name ?? me.data?.email ?? "…"}</p>
          {me.data?.full_name && <p className="truncate text-xs text-sidebar-foreground/70">{me.data.email}</p>}
        </div>
        <button
          type="button"
          onClick={() => {
            logout();
            onNavigate?.();
            navigate("/login", { replace: true });
          }}
          className="rounded-md p-2 text-sidebar-foreground hover:bg-sidebar-accent hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Log out"
          title="Log out"
        >
          <LogOut className="size-4" />
        </button>
      </div>
    </div>
  );
}
