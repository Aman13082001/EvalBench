"use client";

import Link from "next/link";
import { useAuth } from "@/components/AuthProvider";
import StatusStrip from "@/components/StatusStrip";
import ThemeToggle from "@/components/ThemeToggle";

/* One public link. The example evaluation is reached from the study,
   not the nav — a visitor's path is home → study → example → sign in. */
const PUBLIC = [{ href: "/research", label: "Research" }];

const PRIVATE = [
  { href: "/workbench", label: "Workbench" },
  { href: "/suites", label: "Benchmarks" },
  { href: "/dashboard", label: "Dashboard" },
];

export default function Nav() {
  const { user, signOut } = useAuth();

  return (
    <nav className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {PUBLIC.map((n) => (
        <Link
          key={n.href}
          href={n.href}
          className="font-mono text-xs text-muted transition-colors hover:text-text"
        >
          {n.label}
        </Link>
      ))}

      {user &&
        PRIVATE.map((n) => (
          <Link
            key={n.href}
            href={n.href}
            className="font-mono text-xs text-muted transition-colors hover:text-text"
          >
            {n.label}
          </Link>
        ))}

      {user?.role === "admin" && (
        <Link
          href="/admin"
          className="font-mono text-xs text-muted transition-colors hover:text-text"
        >
          Admin
        </Link>
      )}

      <StatusStrip />

      {user ? (
        <button
          onClick={signOut}
          className="font-mono text-xs text-muted transition-colors hover:text-text"
          title={`Signed in as ${user.username}`}
        >
          sign out
        </button>
      ) : (
        <Link
          href="/login"
          className="font-mono text-xs text-accent transition-colors hover:text-text"
        >
          sign in
        </Link>
      )}

      <ThemeToggle />
    </nav>
  );
}
