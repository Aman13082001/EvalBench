"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { login, register } from "@/lib/auth";
import { useAuth } from "@/components/AuthProvider";

/* Sign in without leaving the page. The scrim stays light enough that
   the architecture is still readable behind it — the point is that you
   have not gone anywhere. /login remains a real route so a direct link
   still opens something. */
export default function LoginDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const { refresh, user } = useAuth();
  const panelRef = useRef<HTMLDivElement>(null);
  const firstFieldRef = useRef<HTMLInputElement>(null);

  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState<string | null>(null);

  /* Escape closes; focus lands in the form rather than on the page
     behind it. Both are the difference between a dialog and a div. */
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const t = setTimeout(() => firstFieldRef.current?.focus(), 30);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      clearTimeout(t);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  const submit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError(null);
      setBusy(true);
      try {
        if (mode === "signup") {
          const { api_key } = await register(username, password);
          setApiKey(api_key);
          await login(username, password);
          await refresh();
        } else {
          await login(username, password);
          await refresh();
          onClose();
          router.push("/workbench");
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [mode, username, password, refresh, onClose, router]
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="login-heading"
      onMouseDown={(e) => {
        if (!panelRef.current?.contains(e.target as Node)) onClose();
      }}
    >
      {/* light scrim — the page stays legible underneath */}
      <div className="absolute inset-0 bg-bg/70 backdrop-blur-[2px]" />

      <div
        ref={panelRef}
        className="panel relative w-full max-w-sm shadow-none"
      >
        <header className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 id="login-heading" className="font-display text-base leading-none">
            {mode === "signin" ? "Sign in" : "Create an account"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="label-xs text-muted hover:text-text"
          >
            esc
          </button>
        </header>

        <div className="space-y-3 p-4">
          {apiKey ? (
            <div className="space-y-2">
              <p className="text-sm">
                Account created. This is your API key for CI — it is shown
                once.
              </p>
              <code className="block break-all border border-line bg-surface-sunk p-2 font-mono text-xs">
                {apiKey}
              </code>
              {/* Enabled once the sign-in behind the key has landed; before
                  that, continuing would reach the workbench signed out. */}
              <button
                className="btn btn-primary w-full"
                disabled={!user}
                onClick={() => {
                  onClose();
                  router.push("/workbench");
                }}
              >
                {user ? "Continue" : "Signing you in…"}
              </button>
            </div>
          ) : (
            <>
              <form onSubmit={submit} className="space-y-3">
                <div className="space-y-1">
                  <label className="label-xs block" htmlFor="dlg-user">
                    Username
                  </label>
                  <input
                    id="dlg-user"
                    ref={firstFieldRef}
                    className="field font-mono text-sm"
                    autoComplete="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-1">
                  <label className="label-xs block" htmlFor="dlg-pass">
                    Password
                  </label>
                  <input
                    id="dlg-pass"
                    type="password"
                    className="field font-mono text-sm"
                    autoComplete={
                      mode === "signup" ? "new-password" : "current-password"
                    }
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={mode === "signup" ? 8 : undefined}
                  />
                  {mode === "signup" && (
                    <p className="font-mono text-[11px] text-muted">at least 8 characters</p>
                  )}
                </div>

                {error && (
                  <p className="border border-error px-2 py-1.5 text-xs text-error">
                    {error}
                  </p>
                )}

                <button
                  className="btn btn-primary w-full"
                  disabled={busy}
                  type="submit"
                >
                  {busy
                    ? "…"
                    : mode === "signin"
                      ? "Sign in"
                      : "Create account"}
                </button>
              </form>

              <button
                type="button"
                className="w-full text-center text-xs text-muted hover:text-text"
                onClick={() => {
                  setMode(mode === "signin" ? "signup" : "signin");
                  setError(null);
                }}
              >
                {mode === "signin"
                  ? "No account? Create one"
                  : "Already have an account? Sign in"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
