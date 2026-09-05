"use client";

import { useState } from "react";

import { BoundChecks } from "@/components/BoundChecks";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, approveOrder, declineOrder } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { BoundCheck, Money, Order } from "@/lib/types";

type State = "idle" | "approving" | "declining" | "approved" | "declined" | "error";

/**
 * The human approval gate.
 *
 * Approval is a POST to `/orders/{id}/approve`, tied to a specific order id —
 * it is never inferred from the buyer typing "yes" in the chat. A confirmation
 * the model reads out of conversation text is one a prompt injection can forge;
 * a button press is an action only the person at the keyboard can take.
 */
export function ApprovalPrompt({
  orderId,
  total,
  productName,
  reason,
  checks,
  onResolved,
}: {
  orderId: string;
  total: Money;
  productName: string;
  reason?: string | null;
  checks?: BoundCheck[];
  onResolved?: (order: Order) => void;
}) {
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState<string | null>(null);

  const busy = state === "approving" || state === "declining";
  const settled = state === "approved" || state === "declined";

  async function act(kind: "approve" | "decline") {
    setError(null);
    setState(kind === "approve" ? "approving" : "declining");
    try {
      const { order } =
        kind === "approve"
          ? await approveOrder(orderId)
          : await declineOrder(orderId);
      setState(kind === "approve" ? "approved" : "declined");
      onResolved?.(order);
    } catch (cause) {
      const message =
        cause instanceof ApiError
          ? (cause.detail?.message ?? cause.message)
          : cause instanceof Error
            ? cause.message
            : "Could not record that decision.";
      setError(message);
      setState("error");
    }
  }

  return (
    <Card className="border-warn/30 bg-warn/[0.04] p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-eyebrow uppercase text-warn">Waiting on you</p>
          <h3 className="mt-2 text-title">Approve this purchase?</h3>
          <p className="mt-1.5 text-[0.8125rem] text-muted">{productName}</p>
        </div>
        <span className="tabular shrink-0 whitespace-nowrap text-2xl font-semibold tracking-[-0.03em]">
          {total.display}
        </span>
      </div>

      {reason ? (
        <p className="mt-4 max-w-prose text-[0.8125rem] leading-relaxed text-muted">
          {reason}
        </p>
      ) : null}

      {checks && checks.length > 0 ? (
        <BoundChecks checks={checks} className="mt-3" />
      ) : null}

      {error ? <p className="mt-3 text-[0.75rem] text-danger">{error}</p> : null}

      {settled ? (
        <p
          className={cn(
            "mt-5 flex items-center gap-2 text-[0.8125rem] font-medium",
            state === "approved" ? "text-ok" : "text-muted",
          )}
        >
          <span
            aria-hidden
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              state === "approved" ? "bg-ok" : "bg-faint",
            )}
          />
          {state === "approved"
            ? "Approved — the order was placed."
            : "Declined — nothing was charged."}
        </p>
      ) : (
        <div className="mt-5 flex flex-wrap items-center gap-2.5">
          <Button size="sm" disabled={busy} onClick={() => act("approve")}>
            {state === "approving" ? <Spinner /> : null}
            Approve {total.display}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => act("decline")}
          >
            {state === "declining" ? <Spinner /> : null}
            Decline
          </Button>
        </div>
      )}
    </Card>
  );
}
