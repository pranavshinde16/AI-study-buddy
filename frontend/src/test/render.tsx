import { render } from "@testing-library/react";
import { RouterProvider, createMemoryRouter, type RouteObject } from "react-router-dom";

import { setToken } from "@/api/auth";
import { createQueryClient } from "@/api/queryClient";
import { AppProviders } from "@/app/AppProviders";
import { routes as appRoutes } from "@/routes";

/** Renders the app (or given routes) at `path` with a fresh query cache and toasts. */
export function renderApp(path: string, opts: { routes?: RouteObject[]; loggedIn?: boolean } = {}) {
  if (opts.loggedIn ?? true) setToken("test-token", 3600);
  const client = createQueryClient();
  const router = createMemoryRouter(opts.routes ?? appRoutes, { initialEntries: [path] });
  const utils = render(
    <AppProviders client={client}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return { ...utils, router, client };
}

export const fakeUser = {
  id: "00000000-0000-0000-0000-000000000001",
  email: "ada@example.com",
  full_name: "Ada",
  is_active: true,
  created_at: "2026-11-07T10:00:00Z",
};
