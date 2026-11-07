import { useState, type FormEvent } from "react";
import { Loader2, LogIn } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { isApiError } from "@/api/client";
import { useLogin } from "@/api/hooks";
import { FormField } from "@/components/FormField";
import { Button } from "@/components/ui/button";
import { describeError } from "@/lib/notify";
import { safeNext } from "@/lib/safeNext";
import { validateEmail } from "@/lib/validation";
import { AuthLayout } from "./AuthLayout";

export function LoginPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string | null; password?: string | null }>({});

  const next = safeNext(params.get("next"));
  const expired = params.get("reason") === "expired";

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const found = { email: validateEmail(email), password: password ? null : "Enter your password" };
    setErrors(found);
    if (found.email || found.password) return;
    login.mutate({ email: email.trim(), password }, { onSuccess: () => navigate(next, { replace: true }) });
  }

  const formError = login.error
    ? isApiError(login.error, "INVALID_CREDENTIALS")
      ? "Wrong email or password."
      : describeError(login.error).description
    : null;

  return (
    <AuthLayout title="Log in" subtitle="Welcome back. Pick up where you left off.">
      {expired && (
        <p role="status" className="rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning">
          Your session expired. Please log in again.
        </p>
      )}
      <form className="space-y-4" onSubmit={onSubmit} noValidate>
        <FormField
          id="email"
          label="Email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={errors.email}
        />
        <FormField
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={errors.password}
        />
        {formError && (
          <p role="alert" className="rounded-xl bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {formError}
          </p>
        )}
        <Button type="submit" className="w-full" disabled={login.isPending}>
          {login.isPending ? <Loader2 className="animate-spin" /> : <LogIn />}
          Log in
        </Button>
      </form>
      <p className="text-center text-sm text-muted-foreground">
        No account?{" "}
        <Link to="/register" className="font-medium text-primary hover:underline">
          Register
        </Link>
      </p>
    </AuthLayout>
  );
}
