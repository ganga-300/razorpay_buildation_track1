import { Card } from "@/components/ui/Card";
import { cn } from "@/lib/cn";
import type { BudgetSnapshot } from "@/lib/types";

/** Visual position against the rolling daily cap — "bounded", made legible. */
export function SpendMeter({ budget }: { budget: BudgetSnapshot }) {
  const pct = Math.round(budget.used_fraction * 100);
  const tone =
    pct >= 90 ? "bg-danger" : pct >= 70 ? "bg-warn" : "bg-brand";

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">
          Agent spend, last {budget.window_hours}h
        </h2>
        <p className="text-xs text-muted">
          <span className="font-semibold tabular-nums text-ink">
            {budget.spent.display}
          </span>{" "}
          of {budget.cap.display} · {budget.remaining.display} left
        </p>
      </div>

      <div
        className="mt-3 h-2 w-full overflow-hidden rounded-full bg-surface"
        role="meter"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Daily spend: ${pct}% of cap used`}
      >
        <div
          className={cn("h-full rounded-full transition-all", tone)}
          style={{ width: `${Math.max(pct, budget.spent.amount_minor > 0 ? 2 : 0)}%` }}
        />
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Auto-approve</dt>
          <dd className="tabular-nums">{budget.auto_approve_limit.display}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Per transaction</dt>
          <dd className="tabular-nums">{budget.per_transaction_cap.display}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Daily cap</dt>
          <dd className="tabular-nums">{budget.cap.display}</dd>
        </div>
      </dl>
    </Card>
  );
}
