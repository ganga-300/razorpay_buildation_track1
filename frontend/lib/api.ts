/**
 * Typed client for the AutoBuy backend.
 *
 * Every network call in the app goes through `apiFetch`, so error handling,
 * base-URL resolution, and JSON parsing exist in exactly one place. The only
 * exception is `lib/sse.ts`, which must read a response stream directly.
 */

import type {
  ApprovalResponse,
  AuditListResponse,
  Grant,
  GrantListResponse,
  HealthResponse,
  Order,
  OrderListResponse,
  VerifyPaymentResponse,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** Thrown for any non-2xx response, carrying the status for callers to branch on. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** The backend's structured `{code, message}` detail, when it sent one. */
  get detail(): { code?: string; message?: string } | undefined {
    const body = this.body as { detail?: unknown } | undefined;
    const detail = body?.detail;
    return typeof detail === "object" && detail !== null
      ? (detail as { code?: string; message?: string })
      : undefined;
  }
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (cause) {
    // A dead backend is the most common local failure; say so plainly rather
    // than surfacing an opaque "Failed to fetch".
    throw new ApiError(
      `Cannot reach the backend at ${API_BASE_URL}. Is it running?`,
      0,
      cause,
    );
  }

  if (!res.ok) {
    const body = await res.json().catch(() => undefined);
    throw new ApiError(
      `Request to ${path} failed with ${res.status}`,
      res.status,
      body,
    );
  }

  return (await res.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health", { cache: "no-store" });
}

export function getOrders(): Promise<OrderListResponse> {
  return apiFetch<OrderListResponse>("/orders", { cache: "no-store" });
}

export function getOrder(orderId: string): Promise<Order> {
  return apiFetch<Order>(`/orders/${orderId}`, { cache: "no-store" });
}

export function verifyPayment(payload: {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}): Promise<VerifyPaymentResponse> {
  return apiFetch<VerifyPaymentResponse>("/payments/verify", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface AuditFilters {
  order_id?: string;
  decision?: string;
  outcome?: string;
  action?: string;
}

export function getAudit(filters: AuditFilters = {}): Promise<AuditListResponse> {
  const query = new URLSearchParams(
    Object.entries(filters).filter(([, v]) => Boolean(v)) as [string, string][],
  ).toString();
  return apiFetch<AuditListResponse>(`/audit${query ? `?${query}` : ""}`, {
    cache: "no-store",
  });
}

export function approveOrder(
  orderId: string,
  actor = "buyer",
): Promise<ApprovalResponse> {
  return apiFetch<ApprovalResponse>(`/orders/${orderId}/approve`, {
    method: "POST",
    body: JSON.stringify({ actor }),
  });
}

export function declineOrder(
  orderId: string,
  actor = "buyer",
  reason?: string,
): Promise<ApprovalResponse> {
  return apiFetch<ApprovalResponse>(`/orders/${orderId}/decline`, {
    method: "POST",
    body: JSON.stringify({ actor, reason: reason ?? null }),
  });
}

// ---------------------------------------------------------- consent

export function getGrants(): Promise<GrantListResponse> {
  return apiFetch<GrantListResponse>("/grants", { cache: "no-store" });
}

export function grantAccess(payload: {
  spend_cap_minor: number;
  expires_in_hours: number;
  note?: string;
}): Promise<Grant> {
  return apiFetch<Grant>("/grants", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function revokeGrant(
  grantId: string,
  actor = "buyer",
  reason?: string,
): Promise<Grant> {
  return apiFetch<Grant>(`/grants/${grantId}/revoke`, {
    method: "POST",
    body: JSON.stringify({ actor, reason: reason ?? null }),
  });
}
