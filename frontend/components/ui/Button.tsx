import { cn } from "@/lib/cn";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

/**
 * Fully rounded, like the reference's launch pill. A capsule reads as a
 * deliberate object rather than a default form control, and at these sizes the
 * shape does more work than colour.
 */
const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand text-on-brand hover:opacity-90 active:opacity-100 disabled:opacity-40",
  secondary:
    "border border-border bg-elevated text-ink hover:border-ink/30 hover:bg-sunken disabled:opacity-40",
  ghost: "text-muted hover:text-ink hover:bg-sunken disabled:opacity-40",
  danger: "bg-danger text-white hover:opacity-90 disabled:opacity-40",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 gap-1.5 px-3.5 text-xs",
  md: "h-10 gap-2 px-5 text-sm",
  lg: "h-12 gap-2 px-7 text-[0.9375rem]",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export function Button({
  variant = "primary",
  size = "md",
  className,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex items-center justify-center rounded-full font-medium",
        "whitespace-nowrap tracking-[-0.01em]",
        // A press that moves is a press you felt.
        "transition-[opacity,transform,background-color,border-color] duration-fast ease",
        "active:scale-[0.98] disabled:cursor-not-allowed disabled:active:scale-100",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    />
  );
}
