"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/cn";

/**
 * The floating product card in the hero.
 *
 * Composed in markup rather than screenshotted, so it stays legible at any size
 * and in either theme. It shows the artefact this project is actually about — a
 * spend decision with its bounds — and animates the checks resolving in
 * sequence, because watching a limit fail explains the idea faster than a
 * paragraph does.
 */

const CHECKS = [
  { name: "Agent authority", observed: "₹1,299.00", limit: "₹5,000.00", passed: true },
  { name: "Per-transaction cap", observed: "₹1,299.00", limit: "₹2,000.00", passed: true },
  { name: "Daily cap (24h)", observed: "₹1,648.00", limit: "₹10,000.00", passed: true },
  { name: "Auto-approve limit", observed: "₹1,299.00", limit: "₹500.00", passed: false },
] as const;

export function GuardrailPreview() {
  const [revealed, setRevealed] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || typeof IntersectionObserver === "undefined") {
      setRevealed(CHECKS.length);
      return;
    }

    let timers: ReturnType<typeof setTimeout>[] = [];
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        observer.disconnect();
        // Stagger the rows so the failing bound lands last and is noticed.
        timers = CHECKS.map((_, i) =>
          setTimeout(() => setRevealed(i + 1), 420 + i * 260),
        );
      },
      { threshold: 0.3 },
    );

    observer.observe(node);
    return () => {
      observer.disconnect();
      timers.forEach(clearTimeout);
    };
  }, []);

  return (
    <div
      ref={ref}
      className="rounded-2xl border border-border bg-elevated p-5 shadow-lift sm:p-6"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-eyebrow uppercase text-faint">Spend decision</p>
          <p className="mt-2 font-mono text-[0.75rem] text-muted">
            create_order · prd-wireless-mouse
          </p>
        </div>
        <div className="text-right">
          <p className="tabular text-xl font-semibold tracking-[-0.03em]">
            ₹1,299.00
          </p>
          <p className="mt-1 text-[0.6875rem] font-medium text-warn">
            approval required
          </p>
        </div>
      </div>

      <div className="mt-5 space-y-0.5">
        {CHECKS.map((check, i) => {
          const shown = i < revealed;
          return (
            <div
              key={check.name}
              className={cn(
                "flex items-center gap-3 rounded-lg px-2 py-2 text-[0.75rem]",
                "transition-all duration-slow ease",
                shown ? "opacity-100 blur-0" : "translate-y-1 opacity-0 blur-[2px]",
                !check.passed && shown && "bg-danger/[0.06]",
              )}
            >
              <span
                aria-hidden
                className={cn(
                  "h-1.5 w-1.5 shrink-0 rounded-full transition-colors duration-slow",
                  check.passed ? "bg-ok" : "bg-danger",
                )}
              />
              <span className="text-muted">{check.name}</span>
              <span
                className={cn(
                  "tabular ml-auto whitespace-nowrap",
                  check.passed ? "text-faint" : "font-medium text-danger",
                )}
              >
                {check.observed} / {check.limit}
              </span>
            </div>
          );
        })}
      </div>

      <p
        className={cn(
          "mt-4 border-t border-border pt-4 text-[0.75rem] leading-relaxed text-muted",
          "transition-opacity duration-slow ease",
          revealed >= CHECKS.length ? "opacity-100" : "opacity-0",
        )}
      >
        Above the auto-approve limit, so the order is held and nothing is
        charged until a human approves it.
      </p>
    </div>
  );
}
