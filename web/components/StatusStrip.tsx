"use client";

import { useEffect, useState } from "react";
import { API_URL } from "@/lib/api";

/** Instrument status readout — real, from the API. Quiet when healthy. */
export default function StatusStrip() {
  const [ok, setOk] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    fetch(`${API_URL}/health`)
      .then((r) => alive && setOk(r.ok))
      .catch(() => alive && setOk(false));
    return () => {
      alive = false;
    };
  }, []);

  const dot =
    ok === null ? "text-muted" : ok ? "text-success" : "text-error";
  const text =
    ok === null ? "connecting" : ok ? "api online" : "api unreachable";

  return (
    <span className="hidden items-center gap-1.5 font-mono text-[11px] text-muted sm:inline-flex">
      <span className={dot} aria-hidden>
        ●
      </span>
      {text}
    </span>
  );
}
