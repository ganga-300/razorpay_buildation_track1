"use client";

import { useState } from "react";

import { BoundChecks } from "@/components/BoundChecks";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, approveOrder, declineOrder } from "@/lib/api";
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
    <Card className="border-warn/50 bg-warn/5 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-medium text-warn">
            Your approval is needed
          </h3>
          <p className="mt-0.5 text-xs text-muted">
            {productName} · <span className="font-medium">{total.display}</span>
          </p>
        </div>
        <span className="whitespace-nowrap text-sm font-semibold tabular-nums">
          {total.display}
        </span>
      </div>

      {reason ? (
        <p className="mt-2 text-xs leading-relaxed text-muted">{reason}</p>
      ) : null}

      {checks && checks.length > 0 ? (
        <BoundChecks checks={checks} className="mt-2" />
      ) : null}

      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}

      {settled ? (
        <p className="mt-3 text-xs font-medium">
          {state === "approved"
            ? "Approved — the order was placed."
            : "Declined — nothing was charged."}
        </p>
      ) : (
        <div className="mt-3 flex items-center gap-2">
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
