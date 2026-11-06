import { Navigate, type RouteObject } from "react-router-dom";

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
import { lectureTabs } from "@/pages/lecture/tabs";

/** Every route from IMPLEMENTATION_PLAN.md §9. Exported so tests can use a memory router. */
export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
  {
    element: <AppShell />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "upload", element: <UploadPage /> },
      { path: "lectures/:id/processing", element: <ProcessingPage /> },
      {
        path: "lectures/:id",
        element: <LectureWorkspace />,
        children: [
          { index: true, element: <Navigate to="transcript" replace /> },
          ...lectureTabs.map((tab) => ({ path: tab.path, element: <LectureTabPage tab={tab} /> })),
        ],
      },
      { path: "analytics", element: <AnalyticsPage /> },
      { path: "llmops", element: <LlmOpsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
