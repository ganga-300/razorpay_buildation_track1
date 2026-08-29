/** Types mirroring the backend Pydantic schemas. */

// ---------------------------------------------------------------- money

/**
 * An amount from the API. `amountMinor` is the integer count of the currency's
 * minor unit (paise) and is the only field safe to compare or sum. `display` is
 * a pre-formatted string for rendering — never parse it.
 */
export interface Money {
  amount_minor: number;
  currency: string;
  display: string;
}

// -------------------------------------------------------------- catalog

export interface Availability {
  in_stock: boolean;
  quantity: number;
}

export interface Product {
  id: string;
  name: string;
  description: string;
  category: string;
  price: Money;
  availability: Availability;
  attributes: Record<string, unknown>;
  self_link: string;
}

export interface PurchasePolicy {
  currency: string;
  auto_approve_limit: Money;
  per_transaction_cap: Money;
  daily_cap: Money;
  approval_required_above: Money;
  enforcement: "server-side";
}

// --------------------------------------------------------------- orders

export const ORDER_STATUSES = [
  "pending_approval",
  "created",
  "awaiting_payment",
  "paid",
  "failed",
  "cancelled",
  "blocked",
] as const;

export type OrderStatus = (typeof ORDER_STATUSES)[number];

export interface OrderFailure {
  code: string | null;
  reason: string | null;
}

export interface Order {
  order_id: string;
  status: OrderStatus;
  product: { id: string; name: string };
  quantity: number;
  unit_price: Money;
  total: Money;
  razorpay_order_id: string | null;
  razorpay_payment_id: string | null;
  receipt: string;
  conversation_id?: string | null;
  attempts: number;
  failure: OrderFailure | null;
  created_at: string | null;
  /** Present only on the order returned by `create_order`. */
  checkout?: CheckoutParams;
}

export interface CheckoutParams {
  key_id: string;
  razorpay_order_id: string;
  amount_minor: number;
  currency: string;
  name: string;
  description: string;
}

export interface OrderSummary {
  total_orders: number;
  by_status: Partial<Record<OrderStatus, number>>;
  settled_total: Money;
  pending_total: Money;
}

export interface OrderListResponse {
  count: number;
  summary: OrderSummary;
  orders: Order[];
}

export interface VerifyPaymentResponse {
  verified: boolean;
  order: Order;
}

// ----------------------------------------------------------- chat / SSE

export type AgentIntent = "browse" | "purchase" | "verify" | "cancel" | "other";

export interface ErrorPayload {
  code: string;
  message: string;
  retryable?: boolean;
}

/** Discriminated union of every event `POST /chat` can emit. */
export type ChatEvent =
  | { event: "conversation"; data: { conversation_id: string } }
  | { event: "intent"; data: { intent: AgentIntent } }
  | { event: "message"; data: { text: string } }
  | {
      event: "tool_call";
      data: {
        tool: string;
        arguments: Record<string, unknown>;
        mutates_money: boolean;
      };
    }
  | {
      event: "tool_result";
      data: { tool: string; ok: boolean; error: ErrorPayload | null };
    }
  | { event: "products"; data: { products: Product[] } }
  | { event: "order"; data: { order: Order } }
  | { event: "done"; data: { text: string; intent: AgentIntent | null } }
  | { event: "error"; data: ErrorPayload }
  | { event: "end"; data: { conversation_id: string } };

export type ChatEventName = ChatEvent["event"];

// ---------------------------------------------------------------- health

export interface DependencyStatus {
  name: string;
  configured: boolean;
  reachable: boolean | null;
  detail: string | null;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  app: string;
  environment: string;
  version: string;
  timestamp: string;
  dependencies: DependencyStatus[];
}
