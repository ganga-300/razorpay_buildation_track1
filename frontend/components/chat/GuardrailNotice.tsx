import { BoundChecks } from "@/components/BoundChecks";
import { cn } from "@/lib/cn";
import type { GuardrailDecision } from "@/lib/types";

/** A guardrail verdict, shown inline so the buyer sees why, not just what. */
export function GuardrailNotice({
  decision,
  blocked,
}: {
  decision: GuardrailDecision;
  blocked: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border px-4 py-3.5",
        blocked ? "border-danger/25 bg-danger/[0.04]" : "border-border bg-elevated",
      )}
    >
      <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        <span className="text-eyebrow uppercase text-faint">Spend guardrail</span>
        <span
          className={cn(
            "text-[0.6875rem] font-medium",
            blocked ? "text-danger" : "text-ok",
          )}
        >
          {blocked ? "blocked" : "within limits"}
        </span>
        <span className="tabular ml-auto text-[0.9375rem] font-semibold tracking-[-0.02em]">
          {decision.amount.display}
        </span>
      </div>

      <p
        className={cn(
          "mt-2 max-w-prose text-[0.8125rem] leading-relaxed",
          blocked ? "text-danger" : "text-muted",
        )}
      >
        {decision.reason}
      </p>

      <BoundChecks checks={decision.checks} className="mt-3" />
    </div>
  );
}
