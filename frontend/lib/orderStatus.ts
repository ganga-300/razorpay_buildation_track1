/**
 * Presentation for order statuses.
 *
 * Defined once and used by both the chat order card and the dashboard table, so
 * a status can never look settled in one place and pending in the other.
 */

import type { BadgeTone } from "@/components/ui/Badge";
import type { OrderStatus } from "./types";

interface StatusPresentation {
  label: string;
  tone: BadgeTone;
  /** True once no further action can change this order. */
  terminal: boolean;
}

export const ORDER_STATUS: Record<OrderStatus, StatusPresentation> = {
  pending_approval: { label: "Awaiting approval", tone: "warn", terminal: false },
  created: { label: "Created", tone: "neutral", terminal: false },
  awaiting_payment: { label: "Awaiting payment", tone: "brand", terminal: false },
  paid: { label: "Paid", tone: "ok", terminal: true },
  failed: { label: "Failed", tone: "danger", terminal: true },
  cancelled: { label: "Cancelled", tone: "neutral", terminal: true },
  blocked: { label: "Blocked by guardrail", tone: "danger", terminal: true },
};

export function statusOf(status: OrderStatus): StatusPresentation {
  return (
    ORDER_STATUS[status] ?? { label: status, tone: "neutral", terminal: false }
  );
}

/** Only an order awaiting payment can be paid for. */
export function isPayable(status: OrderStatus): boolean {
  return status === "awaiting_payment" || status === "created";
}
