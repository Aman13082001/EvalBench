"use client";

import { useEffect, useState } from "react";
import Reveal from "@/components/Reveal";

export const GRAFANA_URL =
  process.env.NEXT_PUBLIC_GRAFANA_URL || "http://localhost:3000";

// Height of Grafana 10's in-frame panel header, clipped away.
const GRAFANA_HEADER = 34;

/* Every embedded panel is a full Grafana app boot, and a browser will
   only hold a handful of connections open to one host. Mounting all
   twenty-odd at once starved everything below the fold: the top panels
   drew, the rest stayed blank for ever. So panels queue for one of a few
   slots and release it once their frame has loaded. */
const MAX_CONCURRENT = 3;
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
  if (next) next();
  else active = Math.max(0, active - 1);
}

const UID = "evalbench-production";
const SLUG = "evalbench-e28094-production-overview";

/** The viewer's effective theme, tracked live.

    Grafana renders the panel server-side into the iframe, so it has to be
    told which theme to draw. The site has three states — explicit light,
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
   overview, or Grafana's home screen, inside every frame. `/d-solo/`
   is the endpoint that renders one panel and nothing else. */
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
  const [ready, setReady] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const src =
    `${GRAFANA_URL}/d-solo/${UID}/${SLUG}` +
    `?orgId=1&panelId=${id}&theme=${theme}&from=now-${range}&to=now`;

  return (
    <Reveal delay={delay}>
      {(shown) => (
        <PanelFrame
          shown={shown}
          ready={ready}
          setReady={setReady}
          loaded={loaded}
          setLoaded={setLoaded}
          {...{ id, title, note, height, src }}
        />
      )}
    </Reveal>
  );
}

function PanelFrame({
  shown, ready, setReady, loaded, setLoaded, id, title, note, height, src,
}: {
  shown: boolean;
  ready: boolean;
  setReady: (v: boolean) => void;
  loaded: boolean;
  setLoaded: (v: boolean) => void;
  id: number;
  title: string;
  note?: string;
  height: number;
  src: string;
}) {
  useEffect(() => {
    if (!shown || ready) return;
    let cancelled = false;
    acquireSlot().then(() => {
      if (!cancelled) setReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [shown, ready, setReady]);

  // Release the slot when the frame loads — and on a timeout, so one
  // panel that never fires onLoad cannot hold the queue closed.
  useEffect(() => {
    if (!ready || loaded) return;
    const done = () => {
      if (!loaded) {
        setLoaded(true);
        releaseSlot();
      }
    };
    const t = setTimeout(done, 8000);
    return () => clearTimeout(t);
  }, [ready, loaded, setLoaded]);

  return (
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

          {/* Grafana draws its own panel title inside the frame, which
              would repeat the caption above in Grafana's typography. The
              frame is therefore pulled up by the height of that header
              and the overflow clipped, so one title shows, in ours. */}
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

      {note && (
        <p className="border-t border-line px-3 py-2 text-xs text-muted">
          {note}
        </p>
      )}
    </figure>
  );
}
