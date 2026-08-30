import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "brand" | "ok" | "warn" | "danger";

const TONES: Record<BadgeTone, string> = {
  neutral: "border-border text-muted",
  brand: "border-brand/40 text-brand",
  ok: "border-ok/40 text-ok",
  warn: "border-warn/40 text-warn",
  danger: "border-danger/40 text-danger",
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
        "inline-flex items-center whitespace-nowrap rounded-full border",
        "px-2 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
