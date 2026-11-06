import { Link } from "react-router-dom";

import { AuthLayout } from "./AuthLayout";

export function LoginPage() {
  return (
    <AuthLayout title="Log in" subtitle="Welcome back. Sign-in arrives with the auth API (Phase 3) and UI (Phase 8).">
      <div className="rounded-2xl border border-dashed p-6 text-center text-sm text-muted-foreground">
        Login form coming in Phase 8
      </div>
      <p className="text-center text-sm text-muted-foreground">
        No account?{" "}
        <Link to="/register" className="font-medium text-primary hover:underline">
          Register
        </Link>
      </p>
    </AuthLayout>
  );
}
