import { BoundChecks } from "@/components/BoundChecks";
import { Badge } from "@/components/ui/Badge";
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
        "rounded-lg border px-3 py-2 text-xs",
        blocked ? "border-danger/40 bg-danger/5" : "border-border bg-surface",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">Spend guardrail</span>
        <Badge tone={blocked ? "danger" : "ok"}>
          {blocked ? "blocked" : "within limits"}
        </Badge>
        <span className="ml-auto font-semibold tabular-nums">
          {decision.amount.display}
        </span>
      </div>

      <p className={cn("mt-1.5", blocked ? "text-danger" : "text-muted")}>
        {decision.reason}
      </p>

      <BoundChecks checks={decision.checks} className="mt-2" />
    </div>
  );
}
