import { Link } from "react-router-dom";

import { AuthLayout } from "./AuthLayout";

export function RegisterPage() {
  return (
    <AuthLayout title="Create an account" subtitle="Start turning lectures into study material.">
      <div className="rounded-2xl border border-dashed p-6 text-center text-sm text-muted-foreground">
        Registration form coming in Phase 8
      </div>
      <p className="text-center text-sm text-muted-foreground">
        Already registered?{" "}
        <Link to="/login" className="font-medium text-primary hover:underline">
          Log in
        </Link>
      </p>
    </AuthLayout>
  );
}
