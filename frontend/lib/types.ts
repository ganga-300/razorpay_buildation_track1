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

// ------------------------------------------------------------ guardrails

/** One bound as it was evaluated, with the values seen at that moment. */
export interface BoundCheck {
  name: string;
  limit_minor: number;
  observed_minor: number;
  passed: boolean;
  description: string;
  limit_display: string;
  observed_display: string;
}

export type GuardrailVerdict = "allow" | "require_approval" | "block";

export interface GuardrailDecision {
  verdict: GuardrailVerdict;
  reason: string;
  amount: Money;
  checks: BoundCheck[];
}

// ----------------------------------------------------------------- audit

export type AuditDecision = "allow" | "require_approval" | "block";

export type AuditOutcome =
  | "pending"
  | "awaiting_approval"
  | "succeeded"
  | "failed"
  | "blocked"
  | "declined"
  | "expired";

export interface AuditEntry {
  id: string;
  agent_id: string;
  action: string;
  decision: AuditDecision;
  outcome: AuditOutcome;
  conversation_id: string | null;
  order_id: string | null;
  product: { id: string; name: string } | null;
  quantity: number | null;
  amount: Money;
  checks: BoundCheck[];
  reason: string;
  approved_by: string | null;
  approved_at: string | null;
  failure: { code: string | null; reason: string | null } | null;
  attempts: number;
  duration_ms: number | null;
  created_at: string | null;
}

export interface AuditSummary {
  total: number;
  by_decision: Partial<Record<AuditDecision, number>>;
  by_outcome: Partial<Record<AuditOutcome, number>>;
  blocked_amount: Money;
  approved_amount: Money;
}

export interface BudgetSnapshot {
  window_hours: number;
  currency: string;
  spent: Money;
  cap: Money;
  remaining: Money;
  used_fraction: number;
  auto_approve_limit: Money;
  per_transaction_cap: Money;
}

export interface AuditListResponse {
  count: number;
  summary: AuditSummary;
  budget: BudgetSnapshot;
  entries: AuditEntry[];
}

export interface ApprovalResponse {
  order: Order;
  audit_id: string | null;
  approved_by: string | null;
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
  | {
      event: "guardrail";
      data: GuardrailDecision & { blocked: boolean };
    }
  | {
      event: "approval_required";
      data: {
        order_id: string;
        audit_id: string | null;
        total: Money;
        product: { id: string; name: string };
        reason: string | null;
      };
    }
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
