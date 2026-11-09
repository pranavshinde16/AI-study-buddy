/** Small building blocks shared by the LLMOps sections. */
import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export function Section({
  icon: Icon,
  title,
  description,
  actions,
  children,
  className,
}: {
  icon: LucideIcon;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <CardTitle className="flex items-center gap-2">
            <Icon className="size-4 text-primary" /> {title}
          </CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </div>
        {actions}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export function Kpi({
  label,
  value,
  sub,
  loading,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  loading?: boolean;
}) {
  return (
    <Card>
      <CardContent className="space-y-1 pt-5">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        {loading ? <Skeleton className="h-8 w-24" /> : <p className="text-2xl font-semibold tracking-tight">{value}</p>}
        {sub && !loading && <p className="text-xs text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  );
}

export interface Column<T> {
  header: string;
  cell: (row: T) => ReactNode;
  align?: "left" | "right";
  className?: string;
}

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  caption,
  minWidth = "32rem",
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T, i: number) => string;
  caption?: string;
  minWidth?: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" style={{ minWidth }}>
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="text-left text-xs text-muted-foreground">
          <tr className="border-b">
            {columns.map((c) => (
              <th
                key={c.header}
                scope="col"
                className={cn("py-2 pr-3 font-medium last:pr-0", c.align === "right" && "text-right")}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={rowKey(r, i)} className="border-b align-top last:border-0">
              {columns.map((c) => (
                <td
                  key={c.header}
                  className={cn("py-2 pr-3 last:pr-0", c.align === "right" && "text-right tabular-nums", c.className)}
                >
                  {c.cell(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The table view behind a chart (dataviz relief rule: identity is never colour alone). */
export function TableToggle({ children }: { children: ReactNode }) {
  return (
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
        Show table
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

export function Loading({ h = "h-56" }: { h?: string }) {
  return <Skeleton className={cn("w-full", h)} />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">{children}</p>;
}
