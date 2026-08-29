import { cn } from "@/lib/cn";
import type { BoundCheck } from "@/lib/types";

const LABELS: Record<string, string> = {
  per_transaction_cap: "Per-transaction cap",
  daily_cap: "Daily cap (24h)",
  auto_approve_limit: "Auto-approve limit",
};

/**
 * The bounds that were evaluated, with the values seen at the time.
 *
 * This is what turns "blocked" into an explanation. Shown in the chat when a
 * decision affects the buyer, and in the audit trail as the permanent record.
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
    <ul className={cn("space-y-1 text-[11px]", className)}>
      {checks.map((c) => (
        <li key={c.name} className="flex items-baseline gap-2">
          <span
            aria-hidden
            className={cn(
              "mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full",
              c.passed ? "bg-ok" : "bg-danger",
            )}
          />
          <span className="text-muted">{LABELS[c.name] ?? c.name}</span>
          <span
            className={cn(
              "ml-auto whitespace-nowrap tabular-nums",
              c.passed ? "text-muted" : "font-medium text-danger",
            )}
          >
            {c.observed_display} / {c.limit_display}
          </span>
          <span className="sr-only">{c.passed ? "passed" : "failed"}</span>
        </li>
      ))}
    </ul>
  );
}
