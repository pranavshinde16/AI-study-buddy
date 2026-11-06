import type { LucideIcon } from "lucide-react";
import { Construction } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

interface PlaceholderPageProps {
  title: string;
  description: string;
  /** Phase in IMPLEMENTATION_PLAN.md §10 that builds this page. */
  phase: number;
  icon?: LucideIcon;
}

/** Empty-state placeholder for pages built in later phases. Shows no fake data. */
export function PlaceholderPage({ title, description, phase, icon: Icon = Construction }: PlaceholderPageProps) {
  return (
    <section className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </header>
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
          <div className="flex size-12 items-center justify-center rounded-full bg-accent text-accent-foreground">
            <Icon className="size-6" />
          </div>
          <p className="font-medium">Coming in Phase {phase}</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            This page is a placeholder. It gets connected to the API in a later phase.
          </p>
        </CardContent>
      </Card>
    </section>
  );
}
