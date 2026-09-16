"use client";

import { useEffect, useRef, useState } from "react";

/* Reveal on scroll, and — more usefully — mount on scroll.

   The dashboard embeds seventeen Grafana panels. Each iframe boots the
   whole Grafana app, so mounting them all at once makes the page crawl
   before anyone has scrolled to them. `children` is therefore a function
   that only runs once the block is near the viewport: the animation is
   the visible half of a loading strategy, not decoration.

   Honours prefers-reduced-motion by skipping the transition and showing
   the content immediately. */
export default function Reveal({
  children,
  delay = 0,
  className = "",
}: {
  children: (shown: boolean) => React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    if (reduced || typeof IntersectionObserver === "undefined") {
      setShown(true);
      return;
    }

    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true);
          io.disconnect(); // once revealed, stay revealed
        }
      },
      // Start loading a little before it is on screen, so a panel is
      // usually ready by the time it arrives.
      { rootMargin: "240px 0px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={`reveal ${shown ? "reveal-in" : ""} ${className}`}
      style={delay ? { transitionDelay: `${delay}ms` } : undefined}
    >
      {children(shown)}
    </div>
  );
}
