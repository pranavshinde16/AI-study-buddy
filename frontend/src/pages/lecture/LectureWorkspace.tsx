import { Clock, Loader2, SearchX, Trash2 } from "lucide-react";
import { Link, NavLink, Outlet, useNavigate, useParams } from "react-router-dom";

import { ACTIVE_STATUSES, useDeleteLecture, useLecture } from "@/api/hooks";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDuration } from "@/lib/format";
import { notifySuccess } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { lectureTabs } from "./tabs";

/** Lecture workspace: title, status and the tab bar; the active tab renders below via <Outlet />. */
export function LectureWorkspace() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const lecture = useLecture(id);
  const del = useDeleteLecture();

  if (lecture.isError && (lecture.error.code === "LECTURE_NOT_FOUND" || lecture.error.status === 422)) {
    return (
      <EmptyState
        icon={SearchX}
        title="Lecture not found"
        description="It may have been deleted, or it belongs to another account."
        action={
          <Button asChild variant="outline">
            <Link to="/upload">Upload a lecture</Link>
          </Button>
        }
      />
    );
  }
  if (lecture.isError) return <ErrorState error={lecture.error} onRetry={() => void lecture.refetch()} />;

  const l = lecture.data;

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Lecture</p>
          {l ? (
            <h1 className="truncate text-2xl font-semibold tracking-tight" title={l.title}>
              {l.title}
            </h1>
          ) : (
            <Skeleton className="h-8 w-64 max-w-full" />
          )}
          {l && (
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <StatusBadge status={l.status} error={l.error} />
              <span className="inline-flex items-center gap-1">
                <Clock className="size-3" /> {formatDuration(l.duration_sec)}
              </span>
              {l.language && <span>· {l.language}</span>}
              {ACTIVE_STATUSES.has(l.status) && (
                <Link to={`/lectures/${id}/processing`} className="font-medium text-primary hover:underline">
                  View progress
                </Link>
              )}
            </div>
          )}
        </div>
        {l && (
          <ConfirmDialog
            title="Delete this lecture?"
            description={`"${l.title}" and its transcript, notes, quizzes, flashcards, chats and stored recording will be deleted. This can't be undone.`}
            confirmLabel="Delete"
            destructive
            onConfirm={() =>
              del.mutate(id, {
                onSuccess: () => {
                  notifySuccess("Lecture deleted");
                  navigate("/", { replace: true });
                },
              })
            }
            trigger={
              <Button variant="outline" size="sm" className="self-start" disabled={del.isPending}>
                {del.isPending ? <Loader2 className="animate-spin" /> : <Trash2 />}
                Delete
              </Button>
            }
          />
        )}
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
