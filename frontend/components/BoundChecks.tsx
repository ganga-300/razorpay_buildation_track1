import { cn } from "@/lib/cn";
import type { BoundCheck } from "@/lib/types";

const LABELS: Record<string, string> = {
  agent_authority: "Agent authority",
  per_transaction_cap: "Per-transaction cap",
  daily_cap: "Daily cap (24h)",
  auto_approve_limit: "Auto-approve limit",
};

/**
 * The bounds that were evaluated, with the value seen against each limit.
 *
 * This is what turns "blocked" into an explanation. A failing row is tinted and
 * weighted so it reads first — when four bounds are listed and one stopped the
 * purchase, that one is the entire answer.
 */
export function BoundChecks({
  checks,
  className,
}: {
  checks: BoundCheck[];
  className?: string;
}) {
  if (checks.length === 0) return null;

  return (
    <ul className={cn("space-y-px text-[0.75rem]", className)}>
      {checks.map((check) => (
        <li
          key={check.name}
          className={cn(
            "flex items-center gap-2.5 rounded-lg px-2 py-1.5",
            "transition-colors duration-slow ease",
            !check.passed && "bg-danger/[0.06]",
          )}
        >
          <span
            aria-hidden
            className={cn(
              "h-1.5 w-1.5 shrink-0 rounded-full",
              check.passed ? "bg-ok" : "bg-danger",
            )}
          />
          <span className={check.passed ? "text-muted" : "text-ink"}>
            {LABELS[check.name] ?? check.name}
          </span>
          <span
            className={cn(
              "tabular ml-auto whitespace-nowrap",
              check.passed ? "text-faint" : "font-medium text-danger",
            )}
          >
            {check.observed_display} / {check.limit_display}
          </span>
          <span className="sr-only">{check.passed ? "passed" : "failed"}</span>
        </li>
      ))}
    </ul>
  );
}
