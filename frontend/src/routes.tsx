import { Navigate, type RouteObject } from "react-router-dom";

import { GuestOnly, RequireAuth } from "@/components/auth/RequireAuth";
import { AppShell } from "@/components/layout/AppShell";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { LlmOpsPage } from "@/pages/LlmOpsPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { ProcessingPage } from "@/pages/ProcessingPage";
import { UploadPage } from "@/pages/UploadPage";
import { LoginPage } from "@/pages/auth/LoginPage";
import { RegisterPage } from "@/pages/auth/RegisterPage";
import { LectureTabPage } from "@/pages/lecture/LectureTabPage";
import { LectureWorkspace } from "@/pages/lecture/LectureWorkspace";
import { NotesPage } from "@/pages/lecture/NotesPage";
import { TranscriptPage } from "@/pages/lecture/TranscriptPage";
import { lectureTabs, type LectureTab } from "@/pages/lecture/tabs";

/** Tabs built so far; the rest show their placeholder until their half of Phase 8 (or Phase 9). */
function tabElement(tab: LectureTab) {
  if (tab.path === "transcript") return <TranscriptPage />;
  if (tab.path === "notes") return <NotesPage />;
  return <LectureTabPage tab={tab} />;
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
      { index: true, element: <DashboardPage /> },
      { path: "upload", element: <UploadPage /> },
      { path: "lectures/:id/processing", element: <ProcessingPage /> },
      {
        path: "lectures/:id",
        element: <LectureWorkspace />,
        children: [
          { index: true, element: <Navigate to="transcript" replace /> },
          ...lectureTabs.map((tab) => ({ path: tab.path, element: tabElement(tab) })),
        ],
      },
      { path: "analytics", element: <AnalyticsPage /> },
      { path: "llmops", element: <LlmOpsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
