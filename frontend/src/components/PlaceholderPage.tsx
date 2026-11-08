import type { LucideIcon } from "lucide-react";
import { Check, Construction } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

interface PlaceholderPageProps {
  title: string;
  description: string;
  /** Phase in IMPLEMENTATION_PLAN.md §10 that builds this page. */
  phase: number;
  icon?: LucideIcon;
  /** What the page will contain (from IMPLEMENTATION_PLAN.md §9). */
  planned?: string[];
  /** Render without the page title (inside the lecture workspace). */
  embedded?: boolean;
}

/** "Coming soon" page for features built in later phases, so the navigation stays complete. Shows no fake data. */
export function PlaceholderPage({ title, description, phase, icon: Icon = Construction, planned, embedded }: PlaceholderPageProps) {
  return (
    <section className="space-y-6">
      {!embedded && (
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        </header>
      )}
      <Card className="overflow-hidden">
        <div className="bg-gradient-to-br from-accent via-card to-card">
          <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
            <div className="relative">
              <div className="absolute inset-0 scale-[1.8] rounded-full bg-primary/10" />
              <div className="relative flex size-14 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
                <Icon className="size-7" />
              </div>
            </div>
            <Badge>Coming soon · Phase {phase}</Badge>
            <h2 className="text-lg font-semibold">{embedded ? title : `${title} is on the way`}</h2>
            <p className="max-w-md text-sm text-muted-foreground">{description}</p>
            {planned && planned.length > 0 && (
              <ul className="mt-2 grid max-w-lg gap-2 text-left text-sm sm:grid-cols-2">
                {planned.map((p) => (
                  <li key={p} className="flex items-start gap-2 rounded-xl border bg-card px-3 py-2">
                    <Check className="mt-0.5 size-4 shrink-0 text-primary" />
                    <span>{p}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </div>
      </Card>
    </section>
  );
}
