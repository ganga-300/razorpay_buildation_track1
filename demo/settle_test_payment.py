#!/usr/bin/env python3
"""Settle a test-mode order without clicking through Razorpay Checkout.

Recording is iterative, and opening the Checkout modal and filling a test card
by hand every take is slow and easy to fumble on camera. This produces the same
callback Checkout would: it computes the HMAC-SHA256 of "<order_id>|<payment_id>"
with the merchant's key secret — exactly the signature Razorpay sends — and
posts it to `/payments/verify`.

Nothing is bypassed. The server verifies that signature with the same code path
a real callback hits, so a wrong secret produces a `signature_mismatch` and a
failed order, just as a forged callback would.

    python demo/settle_test_payment.py                        # settle the oldest pending order
    python demo/settle_test_payment.py --order ord-abc123     # settle a specific one
    python demo/settle_test_payment.py --forge                # prove a bad signature is rejected

TEST MODE ONLY. It refuses to run against anything but an `rzp_test_` key —
this mints a valid-looking payment callback, and that is only ever appropriate
against a sandbox you own.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import sys
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

TEST_PREFIX = "rzp_test_"


def sign(secret: str, order_id: str, payment_id: str) -> str:
    """The signature Razorpay Checkout returns: HMAC-SHA256 of order|payment."""
    return hmac.new(
        secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Settle a test-mode order.")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--order", help="Local order id; default is the oldest pending.")
    parser.add_argument(
        "--payment-id", default="pay_DEMOSETTLE0001", help="Fake payment id to record."
    )
    parser.add_argument(
        "--forge",
        action="store_true",
        help="Send a signature NOT derived from the secret, to show it is refused.",
    )
    args = parser.parse_args()

    from app.config import settings

    if not settings.razorpay_key_secret:
        sys.exit("RAZORPAY_KEY_SECRET is not set in backend/.env")
    if not settings.razorpay_key_id.startswith(TEST_PREFIX):
        sys.exit(
            f"Refusing to run: RAZORPAY_KEY_ID is not a {TEST_PREFIX} key. "
            "This mints a payment callback and belongs only against a sandbox."
        )

    orders = httpx.get(f"{args.api}/orders", timeout=180, follow_redirects=True).json()
    pending = [o for o in orders["orders"] if o["status"] == "awaiting_payment"]

    if args.order:
        target = next((o for o in orders["orders"] if o["order_id"] == args.order), None)
        if target is None:
            sys.exit(f"No order {args.order!r}")
    elif pending:
        target = pending[-1]
    else:
        sys.exit("No order is awaiting payment. Create one first.")

    rzp_order = target["razorpay_order_id"]
    if not rzp_order:
        sys.exit(f"{target['order_id']} never reached Razorpay — nothing to settle.")

    signature = (
        "0" * 64
        if args.forge
        else sign(settings.razorpay_key_secret, rzp_order, args.payment_id)
    )

    print(f"\n  order     : {target['order_id']}  ({target['total']['display']})")
    print(f"  razorpay  : {rzp_order}")
    print(f"  signature : {'FORGED — expected to be refused' if args.forge else 'valid HMAC-SHA256'}")

    response = httpx.post(
        f"{args.api}/payments/verify",
        json={
            "razorpay_order_id": rzp_order,
            "razorpay_payment_id": args.payment_id,
            "razorpay_signature": signature,
        },
        timeout=120,
    )

    print(f"\n  HTTP {response.status_code}")
    if response.status_code == 200:
        settled = response.json()["order"]
        print(f"  status    : {settled['status']}")
        print(f"  payment   : {settled['razorpay_payment_id']}\n")
    else:
        detail = response.json().get("detail", {})
        print(f"  refused   : {detail.get('code')}")
        print(f"  {detail.get('message')}\n")
        if args.forge:
            print("  That is the point: an unverifiable payment is never treated")
            print("  as a successful one.\n")


if __name__ == "__main__":
    main()
