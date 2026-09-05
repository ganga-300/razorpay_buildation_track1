import { cn } from "@/lib/cn";
import type { OrderSummary } from "@/lib/types";

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "muted";
}) {
  return (
    <div className="px-5 py-6 sm:px-6">
      <p className="text-eyebrow uppercase text-faint">{label}</p>
      {/* Tabular figures so a number changing in place never reflows the row. */}
      <p
        className={cn(
          "tabular mt-3 text-[1.75rem] font-semibold leading-none tracking-[-0.04em]",
          tone === "muted" && "text-muted",
        )}
      >
        {value}
      </p>
      {hint ? <p className="mt-2 text-[0.75rem] text-faint">{hint}</p> : null}
    </div>
  );
}

/**
 * Settled and pending are shown separately on purpose. An order awaiting
 * payment is intent, not spend; adding the two together would overstate what
 * the agent has actually done with the buyer's money.
 */
export function SummaryStats({ summary }: { summary: OrderSummary }) {
  const paid = summary.by_status.paid ?? 0;
  const failed = summary.by_status.failed ?? 0;

  return (
    <div className="grid gap-px overflow-hidden rounded-2xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
      <div className="bg-elevated">
        <Stat label="Orders" value={String(summary.total_orders)} />
      </div>
      <div className="bg-elevated">
        <Stat
          label="Settled"
          value={summary.settled_total.display}
          hint={`${paid} paid`}
        />
      </div>
      <div className="bg-elevated">
        <Stat
          label="Awaiting payment"
          value={summary.pending_total.display}
          hint="intent, not spend"
          tone="muted"
        />
      </div>
      <div className="bg-elevated">
        <Stat
          label="Failed"
          value={String(failed)}
          hint="see reason in table"
          tone={failed === 0 ? "muted" : "default"}
        />
      </div>
    </div>
  );
}
