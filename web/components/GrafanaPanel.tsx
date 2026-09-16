"use client";

import { useEffect, useState } from "react";
import Reveal from "@/components/Reveal";

export const GRAFANA_URL =
  process.env.NEXT_PUBLIC_GRAFANA_URL || "http://localhost:3000";

// Height of Grafana 10's in-frame panel header, clipped away.
const GRAFANA_HEADER = 34;

/* Every embedded panel is a full Grafana app boot: the frame loads the
   whole front end, which then fetches the dashboard and runs the query.
   Two dozen of those at once is more than Grafana will answer calmly —
   under that burst it serves its home page instead of the panel, so
   boxes end up showing "Welcome to Grafana", or another panel entirely.

   So a panel waits for one of a few slots before it is allowed to
   navigate, and releases it once its frame has loaded. This applies to
   *every* navigation, not just the first: changing the time range
   rewrites all twenty-five URLs at once, which was the same stampede by
   another name. */
const MAX_CONCURRENT = 3;
const LOAD_TIMEOUT_MS = 20_000;

let active = 0;
const waiting: (() => void)[] = [];

function acquireSlot(): Promise<void> {
  if (active < MAX_CONCURRENT) {
    active += 1;
    return Promise.resolve();
  }
  return new Promise((resolve) => waiting.push(resolve));
}

function releaseSlot() {
  const next = waiting.shift();
  if (next) next(); // hand the slot straight on rather than free it
  else active = Math.max(0, active - 1);
}

const UID = "evalbench-production";
const SLUG = "evalbench-e28094-production-overview";

/** The viewer's effective theme, tracked live.

    Grafana renders the panel inside the iframe, so it has to be told
    which theme to draw. The site has three states — explicit light,
    explicit dark, and system — and only the first two stamp `data-theme`
    on the root element. */
export function useEffectiveTheme(): "dark" | "light" {
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    const root = document.documentElement;
    const media = window.matchMedia("(prefers-color-scheme: dark)");

    const read = () => {
      const explicit = root.getAttribute("data-theme");
      if (explicit === "dark" || explicit === "light") setTheme(explicit);
      else setTheme(media.matches ? "dark" : "light");
    };

    read();
    const mo = new MutationObserver(read);
    mo.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    media.addEventListener("change", read);
    return () => {
      mo.disconnect();
      media.removeEventListener("change", read);
    };
  }, []);

  return theme;
}

/* A single panel, embedded.

   The URL matters: `/d/<uid>?panelId=N` renders the *whole dashboard*
   and ignores panelId — which is why this page used to show a cropped
   overview inside every frame. `/d-solo/` renders one panel. */
export default function GrafanaPanel({
  id,
  title,
  note,
  range,
  height = 320,
  delay = 0,
}: {
  id: number;
  title: string;
  note?: string;
  range: string;
  height?: number;
  delay?: number;
}) {
  const theme = useEffectiveTheme();
  const src =
    `${GRAFANA_URL}/d-solo/${UID}/${SLUG}` +
    `?orgId=1&panelId=${id}&theme=${theme}&from=now-${range}&to=now`;

  return (
    <Reveal delay={delay}>
      {(shown) => (
        <figure className="panel m-0 flex flex-col">
          <figcaption className="flex items-baseline justify-between gap-3 border-b border-line px-3 py-2">
            <span className="font-display text-sm">{title}</span>
            <a
              href={`${GRAFANA_URL}/d/${UID}/${SLUG}?orgId=1&viewPanel=${id}`}
              target="_blank"
              rel="noreferrer"
              className="label-xs shrink-0 text-muted hover:text-accent"
              title="Open this panel in Grafana"
            >
              P{id} ↗
            </a>
          </figcaption>

          {/* Keyed by src: a new range or theme is a new navigation, so
              the frame remounts and queues for a slot like any other
              rather than all of them moving at once. */}
          <PanelFrame key={src} shown={shown} src={src} title={title} height={height} />

          {note && (
            <p className="border-t border-line px-3 py-2 text-xs text-muted">
              {note}
            </p>
          )}
        </figure>
      )}
    </Reveal>
  );
}

function PanelFrame({
  shown,
  src,
  title,
  height,
}: {
  shown: boolean;
  src: string;
  title: string;
  height: number;
}) {
  const [ready, setReady] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!shown) return;
    let cancelled = false;
    let held = false;
    acquireSlot().then(() => {
      held = true;
      if (cancelled) releaseSlot();
      else setReady(true);
    });
    return () => {
      cancelled = true;
      // Scrolled away mid-queue: give the slot back or it leaks and the
      // queue closes for everyone behind it.
      if (held) releaseSlot();
    };
  }, [shown]);

  // Release on load, or on a timeout — one frame that never fires onLoad
  // must not hold the queue shut.
  useEffect(() => {
    if (!ready || loaded) return;
    const t = setTimeout(() => {
      setLoaded(true);
      releaseSlot();
    }, LOAD_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [ready, loaded]);

  return (
    /* Grafana draws its own panel title inside the frame, which would
       repeat the caption above in a second typeface. The frame is pulled
       up by the height of that header and the overflow clipped. */
    <div
      className="relative w-full overflow-hidden bg-surface-sunk"
      style={{ height }}
    >
      {ready ? (
        <iframe
          src={src}
          title={title}
          className="absolute inset-x-0 w-full border-0"
          style={{ top: -GRAFANA_HEADER, height: height + GRAFANA_HEADER }}
          onLoad={() => {
            if (!loaded) {
              setLoaded(true);
              releaseSlot();
            }
          }}
        />
      ) : (
        /* Waiting to be scrolled to, or queued behind other panels.
           Holding the space keeps the page from jumping. */
        <div className="absolute inset-0 grid place-items-center">
          <span className="font-mono text-[11px] text-muted">
            {shown ? "queued…" : "loads on scroll"}
          </span>
        </div>
      )}
    </div>
  );
}
