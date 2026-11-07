import { useState, type FormEvent } from "react";
import { Loader2, UserPlus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { isApiError } from "@/api/client";
import { useLogin, useRegister } from "@/api/hooks";
import { FormField } from "@/components/FormField";
import { Button } from "@/components/ui/button";
import { describeError, notifySuccess } from "@/lib/notify";
import { PASSWORD_MIN, validateEmail, validateNewPassword } from "@/lib/validation";
import { AuthLayout } from "./AuthLayout";

interface Errors {
  fullName?: string | null;
  email?: string | null;
  password?: string | null;
  confirm?: string | null;
}

export function RegisterPage() {
  const navigate = useNavigate();
  const register = useRegister();
  const login = useLogin();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Errors>({});

  const pending = register.isPending || login.isPending;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const found: Errors = {
      fullName: fullName.length > 200 ? "At most 200 characters" : null,
      email: validateEmail(email),
      password: validateNewPassword(password),
      confirm: confirm !== password ? "The passwords do not match" : null,
    };
    setErrors(found);
    if (Object.values(found).some(Boolean)) return;

    const creds = { email: email.trim(), password };
    register.mutate(
      { ...creds, full_name: fullName.trim() || null },
      {
        // Log straight in so a new user lands on the upload page.
        onSuccess: () =>
          login.mutate(creds, {
            onSuccess: () => {
              notifySuccess("Account created", "Upload your first lecture to get started.");
              navigate("/upload", { replace: true });
            },
          }),
      },
    );
  }

  const err = register.error ?? login.error;
  const formError = err
    ? isApiError(err, "EMAIL_TAKEN")
      ? "An account with this email already exists. Log in instead."
      : describeError(err).description
    : null;

  return (
    <AuthLayout title="Create an account" subtitle="Start turning lectures into study material.">
      <form className="space-y-4" onSubmit={onSubmit} noValidate>
        <FormField
          id="full_name"
          label="Full name (optional)"
          autoComplete="name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          error={errors.fullName}
        />
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
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={errors.password}
          hint={`At least ${PASSWORD_MIN} characters.`}
        />
        <FormField
          id="confirm"
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          error={errors.confirm}
        />
        {formError && (
          <p role="alert" className="rounded-xl bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {formError}
          </p>
        )}
        <Button type="submit" className="w-full" disabled={pending}>
          {pending ? <Loader2 className="animate-spin" /> : <UserPlus />}
          Create account
        </Button>
      </form>
      <p className="text-center text-sm text-muted-foreground">
        Already registered?{" "}
        <Link to="/login" className="font-medium text-primary hover:underline">
          Log in
        </Link>
      </p>
    </AuthLayout>
  );
}
