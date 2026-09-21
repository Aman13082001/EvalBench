"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login, register } from "@/lib/auth";
import { useAuth } from "@/components/AuthProvider";
import { Panel, Rule } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const { refresh } = useAuth();

  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "signup") {
        const { api_key } = await register(username, password);
        setApiKey(api_key);
        await login(username, password);
      } else {
        await login(username, password);
      }
      await refresh();
      if (mode === "signin") router.push("/workbench");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md space-y-6">
      <header className="space-y-1">
        <p className="label-xs">§ Account</p>
        <h1 className="font-display text-3xl">
          {mode === "signin" ? "Sign in" : "Create an account"}
        </h1>
        <p className="text-sm text-muted">
          Free. An account keeps your benchmarks and run history.
        </p>
      </header>

      <Panel>
        <form onSubmit={submit} className="space-y-3">
          <div className="space-y-1">
            <label className="label-xs block" htmlFor="u">
              Username
            </label>
            <input
              id="u"
              className="field font-mono text-sm"
              value={username}
              autoComplete="username"
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <label className="label-xs block" htmlFor="p">
              Password
            </label>
            <input
              id="p"
              type="password"
              className="field font-mono text-sm"
              value={password}
              autoComplete={
                mode === "signup" ? "new-password" : "current-password"
              }
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={mode === "signup" ? 8 : undefined}
            />
            {mode === "signup" && (
              <p className="font-mono text-[11px] text-muted">at least 8 characters</p>
            )}
          </div>

          {error && <p className="text-sm text-error">{error}</p>}

          <button className="btn btn-primary w-full" disabled={busy}>
            {busy
              ? "…"
              : mode === "signin"
                ? "Sign in"
                : "Create account"}
          </button>
        </form>
      </Panel>

      {apiKey && (
        <Panel title="Your API key" fig="!" >
          <p className="text-sm text-muted">
            Save this now — it is shown once and is what the CLI and CI use.
          </p>
          <pre className="mt-2 overflow-x-auto border border-line bg-surface-sunk p-2 font-mono text-xs">
            {apiKey}
          </pre>
          <a href="/workbench" className="btn btn-primary mt-3 inline-block">
            Continue to the Workbench
          </a>
        </Panel>
      )}

      <Rule />
      <button
        className="btn btn-ghost text-sm"
        onClick={() => {
          setMode(mode === "signin" ? "signup" : "signin");
          setError(null);
          setApiKey(null);
        }}
      >
        {mode === "signin"
          ? "Need an account? Create one"
          : "Already have an account? Sign in"}
      </button>
    </div>
  );
}
