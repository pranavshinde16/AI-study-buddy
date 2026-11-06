import { NavLink, Outlet, useParams } from "react-router-dom";

import { cn } from "@/lib/utils";
import { lectureTabs } from "./tabs";

/** Lecture workspace: tab bar for the six lecture tools; the active tab renders below via <Outlet />. */
export function LectureWorkspace() {
  const { id } = useParams();

  return (
    <div className="space-y-6">
      <header>
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Lecture</p>
        <h1 className="truncate text-2xl font-semibold tracking-tight">{id}</h1>
      </header>

      <nav aria-label="Lecture tabs" className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <div className="inline-flex gap-1 rounded-xl bg-muted p-1">
          {lectureTabs.map(({ path, label, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                  isActive ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                )
              }
            >
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
        </div>
      </nav>

      <Outlet />
    </div>
  );
}
