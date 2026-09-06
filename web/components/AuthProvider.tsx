"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { getToken, logout as clearToken, me, Me } from "@/lib/auth";

type AuthState = {
  user: Me | null;
  loading: boolean;
  refresh: () => Promise<void>;
  signOut: () => void;
};

const Ctx = createContext<AuthState>({
  user: null,
  loading: true,
  refresh: async () => {},
  signOut: () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await me());
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const signOut = useCallback(() => {
    clearToken();
    setUser(null);
  }, []);

  return (
    <Ctx.Provider value={{ user, loading, refresh, signOut }}>
      {children}
    </Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);

/** Wrap a page that requires a session. Redirects to /login when absent. */
export function RequireAuth({
  children,
  admin = false,
}: {
  children: React.ReactNode;
  admin?: boolean;
}) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading) {
    return <p className="font-mono text-sm text-muted">checking session…</p>;
  }
  if (!user) return null;
  if (admin && user.role !== "admin") {
    return (
      <div className="panel border-error p-4">
        <p className="text-sm text-error">
          This page requires an admin account. You are signed in as{" "}
          <span className="font-mono">{user.username}</span> ({user.role}).
        </p>
      </div>
    );
  }
  return <>{children}</>;
}
