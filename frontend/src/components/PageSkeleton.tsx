import { Skeleton } from "@/components/ui/skeleton";

/** Shown while a lazily loaded page's code downloads. */
export function PageSkeleton() {
  return (
    <div className="space-y-4" aria-label="Loading page">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-64 w-full rounded-2xl" />
    </div>
  );
}
