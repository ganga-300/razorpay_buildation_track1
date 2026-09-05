import { Card } from "@/components/ui/Card";
import { cn } from "@/lib/cn";
import type { BudgetSnapshot } from "@/lib/types";

/** Visual position against the rolling daily cap — "bounded", made legible. */
export function SpendMeter({ budget }: { budget: BudgetSnapshot }) {
  const pct = Math.round(budget.used_fraction * 100);
  const tone = pct >= 90 ? "bg-danger" : pct >= 70 ? "bg-warn" : "bg-ink";

  return (
    <Card className="p-5 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <div>
          <p className="text-eyebrow uppercase text-faint">
            Agent spend · last {budget.window_hours}h
          </p>
          <p className="tabular mt-3 text-[1.75rem] font-semibold leading-none tracking-[-0.04em]">
            {budget.spent.display}
          </p>
        </div>
        <p className="text-[0.8125rem] text-muted">
          of {budget.cap.display} ·{" "}
          <span className="tabular text-ink">{budget.remaining.display}</span> left
        </p>
      </div>

      <div
        className="mt-5 h-1.5 w-full overflow-hidden rounded-full bg-sunken"
        role="meter"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Daily spend: ${pct}% of cap used`}
      >
        {/* The fill grows rather than appearing, so a change in spend reads as
            movement along the bar instead of a redraw. */}
        <div
          className={cn("h-full rounded-full transition-[width] duration-slow ease", tone)}
          style={{
            width: `${Math.max(pct, budget.spent.amount_minor > 0 ? 1.5 : 0)}%`,
          }}
        />
      </div>

      <dl className="mt-5 grid grid-cols-1 gap-x-8 gap-y-2 border-t border-border pt-4 text-[0.75rem] sm:grid-cols-3">
        {[
          ["Auto-approve", budget.auto_approve_limit.display],
          ["Per transaction", budget.per_transaction_cap.display],
          ["Daily cap", budget.cap.display],
        ].map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3 sm:block">
            <dt className="text-faint">{label}</dt>
            <dd className="tabular sm:mt-1">{value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
