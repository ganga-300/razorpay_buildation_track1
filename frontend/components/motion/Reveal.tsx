"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * Reveals its children when they scroll into view.
 *
 * The content is visible by default and only hidden once the document is marked
 * motion-ready (see `MotionProvider`). A component that hides its own children
 * waiting for an observer will hide them permanently if the script never runs —
 * so the animation is opt-in at runtime, not opt-out.
 *
 * `delay` staggers siblings. Keep it small: a list whose last item arrives a
 * second after the first stops feeling responsive and starts feeling slow.
 */
export function Reveal({
  children,
  delay = 0,
  className,
  as: Tag = "div",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
  as?: "div" | "section" | "li" | "header" | "article";
}) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    // No observer available: show it rather than leaving it hidden forever.
    if (typeof IntersectionObserver === "undefined") {
      node.dataset.shown = "true";
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          node.dataset.shown = "true";
          // Reveal once. Re-animating on scroll-up is a nervous tic.
          observer.unobserve(entry.target);
        }
      },
      { rootMargin: "0px 0px -12% 0px", threshold: 0.05 },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <Tag
      ref={ref as never}
      data-reveal=""
      style={delay ? { transitionDelay: `${delay}ms` } : undefined}
      className={cn(className)}
    >
      {children}
    </Tag>
  );
}
