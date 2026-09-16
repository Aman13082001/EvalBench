"use client";

import Link from "next/link";
import { useAuth } from "@/components/AuthProvider";
import StatusStrip from "@/components/StatusStrip";
import SignIn from "@/components/SignIn";
import ThemeToggle from "@/components/ThemeToggle";

/* One public link. "The study" rather than "Research": it promises one
   specific thing to read, which is both truer and more clickable than a
   category. The example evaluation is reached from the end of the study,
   not the nav — a visitor's path is home → study → example → sign in. */
const PUBLIC = [{ href: "/research", label: "The study" }];

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
        <SignIn className="font-mono text-xs text-accent transition-colors hover:text-text">
          sign in
        </SignIn>
      )}

      <ThemeToggle />
    </nav>
  );
}
