import { Card } from "@/components/ui/Card";
import type { OrderSummary } from "@/lib/types";

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card className="p-4">
      <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
    </Card>
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
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Stat label="Orders" value={String(summary.total_orders)} />
      <Stat
        label="Settled"
        value={summary.settled_total.display}
        hint={`${paid} paid`}
      />
      <Stat
        label="Awaiting payment"
        value={summary.pending_total.display}
        hint="intent, not spend"
      />
      <Stat label="Failed" value={String(failed)} hint="see reason in table" />
    </div>
  );
}
