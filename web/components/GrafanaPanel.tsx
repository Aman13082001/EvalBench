"use client";

import { useEffect, useState } from "react";

/* Unset means there is no Grafana here — the hosted deployment runs one
   API container and no Prometheus — and the operations section stays
   off the page. The compose file sets it; `npm run dev` reads it from
   .env.local. */
export const GRAFANA_URL = process.env.NEXT_PUBLIC_GRAFANA_URL ?? "";
export const HAS_GRAFANA = GRAFANA_URL !== "";

export const UID = "evalbench-production";
export const SLUG = "evalbench-e28094-production-overview";

/* The provisioned dashboard is 121 grid rows tall (grafana/dashboards/
   evalbench.json, max gridPos.y + h). Grafana draws a grid row at 30px
   with an 8px margin under it, plus the kiosk page's own padding. The
   frame is sized to the whole thing so the page scrolls, not the frame. */
const GRID_ROWS = 121;
const DASHBOARD_HEIGHT = GRID_ROWS * (30 + 8) + 72;

/** The viewer's effective theme, tracked live.

    Grafana renders inside the iframe, so it has to be told which theme
    to draw. The site has three states — explicit light, explicit dark,
    and system — and only the first two stamp `data-theme` on <html>;
    system is read from the media query and re-read when it changes. */
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

/* The dashboard, embedded once.

   It used to be twenty-five frames, one per panel, each booting the
   whole Grafana front end. Same-origin frames in one tab share
   Grafana's browser storage, and under that many simultaneous boots
   Grafana's frontend confused itself: a "Total runs" box painting the
   welcome page, a pass-rate gauge painting another panel's number. A
   throttle narrowed the window; it did not close it. One frame closes
   it — nothing to race — and it is one boot instead of twenty-five.

   `kiosk` hides Grafana's own chrome; the rows and panel titles remain,
   and the dashboard's descriptions live in the dashboard. */
export default function GrafanaDashboard({ range }: { range: string }) {
  const theme = useEffectiveTheme();
  const src =
    `${GRAFANA_URL}/d/${UID}/${SLUG}` +
    `?orgId=1&kiosk&theme=${theme}&from=now-${range}&to=now`;

  return (
    <div className="panel overflow-hidden p-0">
      <iframe
        key={src}
        src={src}
        title="EvalBench — production overview (Grafana)"
        className="block w-full border-0"
        style={{ height: DASHBOARD_HEIGHT, background: "transparent" }}
        loading="lazy"
      />
    </div>
  );
}
