"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, verifyPayment } from "@/lib/api";
import { isPayable, statusOf } from "@/lib/orderStatus";
import { openCheckout } from "@/lib/razorpay";
import type { Order } from "@/lib/types";

type PayState = "idle" | "opening" | "verifying" | "done" | "error";

/**
 * An order the agent created, with the checkout handoff.
 *
 * Verification goes to `POST /payments/verify` rather than back through the
 * agent: a signature check is a security control, and a control that only runs
 * if a language model decides to call a tool is not a control.
 */
export function OrderCard({
  order: initial,
  onSettled,
}: {
  order: Order;
  onSettled?: (order: Order) => void;
}) {
  // The prop is the source of truth: when the order is approved elsewhere in
  // the transcript, the parent hands down an updated one. Seeding useState from
  // the prop would freeze this card at the value it first rendered with, so a
  // local copy is kept only for the settlement this card performed itself.
  const [settled, setSettled] = useState<Order | null>(null);
  const order = settled ?? initial;

  const [state, setState] = useState<PayState>("idle");
  const [error, setError] = useState<string | null>(null);

  const presentation = statusOf(order.status);
  const canPay = isPayable(order.status) && Boolean(order.checkout);

  async function handlePay() {
    if (!order.checkout) return;

    setError(null);
    setState("opening");

    try {
      const result = await openCheckout(order.checkout);

      // The buyer dismissed the modal — a normal outcome, not a failure.
      if (result === null) {
        setState("idle");
        return;
      }

      setState("verifying");
      const { order: paid } = await verifyPayment(result);
      setSettled(paid);
      setState("done");
      onSettled?.(paid);
    } catch (cause) {
      const message =
        cause instanceof ApiError
          ? (cause.detail?.message ?? cause.message)
          : cause instanceof Error
            ? cause.message
            : "Payment could not be completed.";
      setError(message);
      setState("error");
    }
  }

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="truncate text-[0.875rem] font-semibold tracking-[-0.015em]">
            {order.quantity} × {order.product.name}
          </h3>
          <code className="mt-1 block font-mono text-[0.6875rem] text-faint">
            {order.order_id}
          </code>
        </div>
        <div className="shrink-0 text-right">
          {/* The amount is the largest thing here. It is what the buyer is
              being asked to agree to. */}
          <div className="tabular whitespace-nowrap text-xl font-semibold tracking-[-0.03em]">
            {order.total.display}
          </div>
          <Badge tone={presentation.tone} className="mt-1.5">
            {presentation.label}
          </Badge>
        </div>
      </div>

      {order.failure?.code ? (
        <p className="mt-3 rounded-lg bg-danger/[0.06] px-3 py-2 text-[0.75rem] leading-relaxed text-danger">
          <span className="font-mono font-medium">{order.failure.code}</span>
          {order.failure.reason ? ` — ${order.failure.reason}` : null}
        </p>
      ) : null}

      {error ? (
        <p className="mt-3 text-[0.75rem] text-danger">{error}</p>
      ) : null}

      {canPay ? (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button
            size="sm"
            onClick={handlePay}
            disabled={state === "opening" || state === "verifying"}
          >
            {state === "verifying" ? (
              <>
                <Spinner /> Verifying…
              </>
            ) : state === "opening" ? (
              <>
                <Spinner /> Opening…
              </>
            ) : (
              `Pay ${order.total.display}`
            )}
          </Button>
          <span className="text-[0.6875rem] text-faint">Razorpay test mode</span>
        </div>
      ) : null}
    </Card>
  );
}
