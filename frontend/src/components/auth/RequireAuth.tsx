import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuthToken } from "@/api/hooks";
import { safeNext } from "@/lib/safeNext";

/** Pages inside the app shell need a token; without one, go to /login and come back afterwards. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const token = useAuthToken();
  const location = useLocation();
  if (!token) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <>{children}</>;
}

/** Login/register: already logged in → go straight to the app. */
export function GuestOnly({ children }: { children: ReactNode }) {
  const token = useAuthToken();
  const location = useLocation();
  if (token) {
    return <Navigate to={safeNext(new URLSearchParams(location.search).get("next"))} replace />;
  }
  return <>{children}</>;
}
