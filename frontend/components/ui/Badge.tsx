import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "brand" | "ok" | "warn" | "danger";

/**
 * A tinted wash rather than an outline. Against a warm paper ground a hairline
 * badge disappears; a faint fill of its own hue reads at a glance without
 * shouting, which matters when several sit in one table cell.
 */
const TONES: Record<BadgeTone, string> = {
  neutral: "bg-sunken text-muted",
  brand: "bg-ink/[0.06] text-ink",
  ok: "bg-ok/10 text-ok",
  warn: "bg-warn/10 text-warn",
  danger: "bg-danger/10 text-danger",
};

export function Badge({
  tone = "neutral",
  children,
  className,
  title,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
  /** Native tooltip, for badges whose meaning is not obvious from the label. */
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full",
        "px-2.5 py-1 text-[0.6875rem] font-medium leading-none tracking-[-0.005em]",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
