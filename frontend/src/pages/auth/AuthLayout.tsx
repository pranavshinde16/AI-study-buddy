import type { ReactNode } from "react";
import { GraduationCap } from "lucide-react";

/** Split-screen layout for login/register: brand hero on the left (lg+), form on the right. */
export function AuthLayout({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-sidebar p-10 text-white lg:flex">
        <div className="flex items-center gap-2 font-semibold">
          <div className="flex size-8 items-center justify-center rounded-lg bg-sidebar-primary">
            <GraduationCap className="size-5" />
          </div>
          AI Study Buddy
        </div>
        <div className="space-y-3">
          <h2 className="text-3xl font-semibold leading-tight">Turn every lecture into a study kit.</h2>
          <p className="text-sidebar-foreground">
            Transcripts, notes, quizzes, flashcards and answers grounded in what your lecturer actually said.
          </p>
        </div>
        <p className="text-xs text-sidebar-foreground/70">University project</p>
      </div>
      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm space-y-6">
          <header className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            <p className="text-sm text-muted-foreground">{subtitle}</p>
          </header>
          {children}
        </div>
      </div>
    </div>
  );
}
