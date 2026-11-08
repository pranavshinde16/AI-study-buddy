import { lazy, Suspense, type ComponentType, type ReactNode } from "react";
import { Navigate, type RouteObject } from "react-router-dom";

import { GuestOnly, RequireAuth } from "@/components/auth/RequireAuth";
import { AppShell } from "@/components/layout/AppShell";
import { PageSkeleton } from "@/components/PageSkeleton";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { LoginPage } from "@/pages/auth/LoginPage";
import { RegisterPage } from "@/pages/auth/RegisterPage";
import { LectureTabPage } from "@/pages/lecture/LectureTabPage";
import { LectureWorkspace } from "@/pages/lecture/LectureWorkspace";
import { lectureTabs, type LectureTab } from "@/pages/lecture/tabs";

/** Code-splitting: each page is its own chunk, loaded on first visit (Recharts only with the charts). */
function page<M extends Record<string, unknown>>(load: () => Promise<M>, name: keyof M & string) {
  const Lazy = lazy(async () => ({ default: (await load())[name] as ComponentType }));
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Lazy />
    </Suspense>
  );
}

const MIND_MAP_PLANNED = [
  "Topics as a tree of concept nodes",
  "Labelled links between related ideas",
  "Automatic layout (React Flow + dagre)",
  "Click a node to read its notes",
];

function tabElement(tab: LectureTab): ReactNode {
  switch (tab.path) {
    case "transcript":
      return page(() => import("@/pages/lecture/TranscriptPage"), "TranscriptPage");
    case "notes":
      return page(() => import("@/pages/lecture/NotesPage"), "NotesPage");
    case "quiz":
      return page(() => import("@/pages/lecture/quiz/QuizPage"), "QuizPage");
    case "ask":
      return page(() => import("@/pages/lecture/ask/AskPage"), "AskPage");
    case "flashcards":
      return page(() => import("@/pages/lecture/flashcards/FlashcardsPage"), "FlashcardsPage");
    default:
      return <LectureTabPage tab={tab} planned={tab.path === "mindmap" ? MIND_MAP_PLANNED : undefined} />;
  }
}

/** Every route from IMPLEMENTATION_PLAN.md §9. Exported so tests can use a memory router. */
export const routes: RouteObject[] = [
  { path: "/login", element: <GuestOnly><LoginPage /></GuestOnly> },
  { path: "/register", element: <GuestOnly><RegisterPage /></GuestOnly> },
  {
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: page(() => import("@/pages/DashboardPage"), "DashboardPage") },
      { path: "upload", element: page(() => import("@/pages/UploadPage"), "UploadPage") },
      { path: "lectures/:id/processing", element: page(() => import("@/pages/ProcessingPage"), "ProcessingPage") },
      {
        path: "lectures/:id",
        element: <LectureWorkspace />,
        children: [
          { index: true, element: <Navigate to="transcript" replace /> },
          ...lectureTabs.map((tab) => ({ path: tab.path, element: tabElement(tab) })),
        ],
      },
      { path: "analytics", element: page(() => import("@/pages/AnalyticsPage"), "AnalyticsPage") },
      { path: "llmops", element: page(() => import("@/pages/LlmOpsPage"), "LlmOpsPage") },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
