"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AdminStats,
  AdminUser,
  adminSetActive,
  adminStats,
  adminUsers,
} from "@/lib/api";
import { RequireAuth, useAuth } from "@/components/AuthProvider";
import { Metric, Panel, Rule, Status } from "@/components/ui";

function Admin() {
  const { user } = useAuth();
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    adminUsers()
      .then((r) => setUsers(r.users))
      .catch((e) => setError(String(e.message ?? e)));
    adminStats()
      .then(setStats)
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  useEffect(load, [load]);

  async function toggle(u: AdminUser) {
    setError(null);
    try {
      await adminSetActive(u.username, !u.active);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <p className="label-xs">§ Admin</p>
        <h1 className="font-display text-3xl">System</h1>
        <p className="text-sm text-muted">
          Signed in as <span className="font-mono text-xs">{user?.username}</span>.
        </p>
      </header>

      {error && (
        <div className="panel border-error p-3 text-sm text-error">{error}</div>
      )}

      {stats && (
        <>
          <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
            <Metric label="Users" value={String(stats.users)} caption="Registered accounts." />
            <Metric label="Suites" value={String(stats.suites)} caption="Saved across all users." />
            <Metric label="Runs" value={String(stats.runs)} caption="Stored run documents." />
            <Metric
              label="Total spend"
              value={`$${stats.total_cost_usd.toFixed(4)}`}
              caption="Estimated, across every stored run."
              tone="accent"
            />
          </div>

          <Panel title="Runs by status" fig="A">
            <div className="flex flex-wrap gap-2">
              {Object.entries(stats.runs_by_status).map(([k, v]) => (
                <Status
                  key={k}
                  state={
                    k === "completed"
                      ? "pass"
                      : k === "failed"
                        ? "fail"
                        : "pending"
                  }
                >
                  {k} {v}
                </Status>
              ))}
            </div>
          </Panel>
        </>
      )}

      <Rule label="Users" />

      {!users && !error && (
        <p className="font-mono text-sm text-muted">loading…</p>
      )}

      <div className="space-y-2">
        {users?.map((u) => (
          <div
            key={u.username}
            className="panel flex flex-wrap items-center justify-between gap-3 p-3"
          >
            <div className="flex items-center gap-3">
              <span className="font-mono text-sm">{u.username}</span>
              <span className="label-xs">{u.role}</span>
              <Status state={u.active ? "pass" : "fail"}>
                {u.active ? "active" : "deactivated"}
              </Status>
            </div>
            <button
              className="btn btn-ghost px-2 py-1 font-mono text-[11px]"
              onClick={() => toggle(u)}
              disabled={u.username === user?.username}
              title={
                u.username === user?.username
                  ? "You cannot deactivate your own account"
                  : undefined
              }
            >
              {u.active ? "deactivate" : "activate"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <RequireAuth admin>
      <Admin />
    </RequireAuth>
  );
}
