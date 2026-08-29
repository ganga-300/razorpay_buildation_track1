/**
 * Razorpay Checkout handoff.
 *
 * The checkout script is injected on demand rather than loaded on every page —
 * most visits never open checkout, and the dashboard never does.
 */

import type { CheckoutParams } from "./types";

const CHECKOUT_SRC = "https://checkout.razorpay.com/v1/checkout.js";

export interface CheckoutResult {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

interface RazorpayHandler {
  open: () => void;
  on: (event: string, cb: (payload: unknown) => void) => void;
}

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => RazorpayHandler;
  }
}

let scriptPromise: Promise<void> | null = null;

/** Load checkout.js once; concurrent callers share the same promise. */
export function loadCheckoutScript(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Checkout is browser-only"));
  }
  if (window.Razorpay) return Promise.resolve();
  if (scriptPromise) return scriptPromise;

  scriptPromise = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = CHECKOUT_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      scriptPromise = null; // allow a retry after a transient network failure
      reject(new Error("Could not load Razorpay Checkout."));
    };
    document.body.appendChild(script);
  });

  return scriptPromise;
}

/**
 * Open Razorpay Checkout and resolve with the values needed for verification.
 *
 * Resolves `null` when the buyer dismisses the modal — a cancellation is a
 * normal outcome, not an error.
 */
export async function openCheckout(
  params: CheckoutParams,
): Promise<CheckoutResult | null> {
  await loadCheckoutScript();

  const Razorpay = window.Razorpay;
  if (!Razorpay) throw new Error("Razorpay Checkout is unavailable.");

  return new Promise<CheckoutResult | null>((resolve, reject) => {
    let settled = false;
    const settle = (value: CheckoutResult | null) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };

    const checkout = new Razorpay({
      key: params.key_id,
      order_id: params.razorpay_order_id,
      amount: params.amount_minor,
      currency: params.currency,
      name: params.name,
      description: params.description,
      handler: (res: CheckoutResult) => settle(res),
      modal: { ondismiss: () => settle(null) },
      theme: { color: "#3b5bdb" },
    });

    checkout.on("payment.failed", (payload: unknown) => {
      if (settled) return;
      settled = true;
      const description =
        (payload as { error?: { description?: string } } | undefined)?.error
          ?.description ?? "The payment did not go through.";
      reject(new Error(description));
    });

    checkout.open();
  });
}
