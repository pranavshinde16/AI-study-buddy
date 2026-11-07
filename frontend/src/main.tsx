import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createBrowserRouter } from "react-router-dom";
import { toast } from "sonner";

import "@fontsource-variable/inter";
import "./index.css";
import { setUnauthorizedHandler } from "./api/client";
import { createQueryClient } from "./api/queryClient";
import { AppProviders } from "./app/AppProviders";
import { routes } from "./routes";

const queryClient = createQueryClient();
const router = createBrowserRouter(routes);

// 401 on a logged-in request: the token is already cleared; drop cached data and go to /login.
setUnauthorizedHandler(() => {
  queryClient.clear();
  const { pathname, search } = router.state.location;
  toast.error("Session expired", { description: "Please log in again." });
  void router.navigate(`/login?next=${encodeURIComponent(pathname + search)}&reason=expired`, { replace: true });
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppProviders client={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>
  </StrictMode>,
);
