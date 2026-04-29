import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useLogin, useRegister } from "@/hooks/use-auth";

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const login = useLogin();
  const register = useRegister();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [loginValue, setLoginValue] = useState("");
  const [password, setPassword] = useState("");
  const [workspace, setWorkspace] = useState("default");
  const [error, setError] = useState<string | null>(null);

  const isPending = login.isPending || register.isPending;
  const redirectTo =
    (location.state as { from?: string } | undefined)?.from ?? "/";

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      if (mode === "login") {
        await login.mutateAsync({
          login: loginValue.trim(),
          password,
        });
      } else {
        await register.mutateAsync({
          login: loginValue.trim(),
          password,
          workspace_name: workspace.trim() || "default",
        });
      }
      navigate(redirectTo, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-4 rounded-lg border bg-card p-6 shadow-sm"
      >
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {mode === "login" ? "Sign in" : "Create workspace"}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {mode === "login"
              ? "Enter your credentials to access the combine panel."
              : "Register a new owner workspace with an admin user."}
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="login-login">Login</Label>
          <Input
            id="login-login"
            value={loginValue}
            onChange={(e) => setLoginValue(e.target.value)}
            autoComplete="username"
            required
            minLength={3}
            maxLength={64}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="login-password">Password</Label>
          <Input
            id="login-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            minLength={8}
            maxLength={256}
          />
        </div>

        {mode === "register" && (
          <div className="space-y-2">
            <Label htmlFor="login-workspace">Workspace name</Label>
            <Input
              id="login-workspace"
              value={workspace}
              onChange={(e) => setWorkspace(e.target.value)}
              maxLength={64}
            />
          </div>
        )}

        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}

        <Button type="submit" className="w-full" disabled={isPending}>
          {isPending
            ? "Please wait…"
            : mode === "login"
              ? "Sign in"
              : "Register"}
        </Button>

        <button
          type="button"
          className="w-full text-xs text-muted-foreground underline"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
        >
          {mode === "login"
            ? "Need an account? Register a new workspace."
            : "Already have an account? Sign in."}
        </button>
      </form>
    </div>
  );
}
