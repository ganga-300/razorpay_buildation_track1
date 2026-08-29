"""Razorpay client wrapper — TEST MODE ONLY.

Three things this layer is responsible for:

1. **Keeping the sync SDK off the event loop.** The `razorpay` package is
   blocking. Every call is dispatched with `asyncio.to_thread`, so a slow
   payment gateway cannot stall the whole FastAPI worker.
2. **Turning SDK exceptions into domain errors.** `RazorpayError` carries a
   stable `code` and a `retryable` flag, which is what the agent's retry-with-
   backoff logic and the audit trail both key off.
3. **Refusing to run against a live account.** The key prefix is re-checked here,
   not only at startup, because this is the last line before real money.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

import razorpay
from razorpay.errors import (
    BadRequestError,
    GatewayError,
    ServerError,
    SignatureVerificationError,
)

from app.config import settings

logger = logging.getLogger(__name__)

TEST_KEY_PREFIX: Final = "rzp_test_"

# Errors worth one retry: transient gateway/infrastructure faults. A bad request
# is deterministic — retrying it just burns time and produces the same failure.
RETRYABLE_SDK_ERRORS: Final = (GatewayError, ServerError)


class RazorpayError(Exception):
    """A payment-provider failure, classified for the agent to act on."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            **({"details": self.details} if self.details else {}),
        }


class RazorpayNotConfigured(RazorpayError):
    """Raised when payment routes are reached without test credentials."""

    def __init__(self) -> None:
        super().__init__(
            "razorpay_not_configured",
            "Razorpay test credentials are not set. Add RAZORPAY_KEY_ID "
            "(rzp_test_...) and RAZORPAY_KEY_SECRET to the backend .env.",
        )


class RazorpayClient:
    """Async facade over the blocking Razorpay SDK."""

    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
    ) -> None:
        self._key_id = key_id if key_id is not None else settings.razorpay_key_id
        self._key_secret = (
            key_secret if key_secret is not None else settings.razorpay_key_secret
        )
        self._client: razorpay.Client | None = None

    # -- lifecycle ---------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self._key_id and self._key_secret)

    def _require_client(self) -> razorpay.Client:
        if not self.configured:
            raise RazorpayNotConfigured()

        if not self._key_id.startswith(TEST_KEY_PREFIX):
            # Belt and braces: config.py already rejects this at startup.
            raise RazorpayError(
                "live_key_refused",
                "Refusing to transact: this project is test-mode only and the "
                f"configured key does not start with {TEST_KEY_PREFIX!r}.",
            )

        if self._client is None:
            self._client = razorpay.Client(auth=(self._key_id, self._key_secret))
            self._client.set_app_details({"title": settings.app_name, "version": "1.0"})
        return self._client

    # -- orders ------------------------------------------------------------

    async def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        receipt: str,
        notes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a Razorpay order. `amount_minor` is paise — never rupees."""
        if amount_minor <= 0:
            raise RazorpayError("invalid_amount", "Order amount must be positive.")

        client = self._require_client()
        payload: dict[str, Any] = {
            "amount": amount_minor,
            "currency": currency,
            "receipt": receipt,
            # Authorise and capture in one step — this demo has no separate
            # capture stage, so leaving payments merely authorised would strand
            # them in a state the audit trail could not resolve.
            "payment_capture": 1,
            "notes": notes or {},
        }

        logger.info(
            "Razorpay order.create receipt=%s amount_minor=%s", receipt, amount_minor
        )
        return await self._call(client.order.create, payload, action="order.create")

    async def fetch_order(self, order_id: str) -> dict[str, Any]:
        client = self._require_client()
        return await self._call(client.order.fetch, order_id, action="order.fetch")

    async def fetch_payment(self, payment_id: str) -> dict[str, Any]:
        client = self._require_client()
        return await self._call(client.payment.fetch, payment_id, action="payment.fetch")

    # -- verification ------------------------------------------------------

    async def verify_payment_signature(
        self, *, order_id: str, payment_id: str, signature: str
    ) -> bool:
        """Verify the HMAC Razorpay Checkout returns after a payment.

        Returns True on a valid signature and raises `RazorpayError` with code
        `signature_mismatch` on an invalid one — a forged or corrupted callback
        must never be indistinguishable from a declined card.
        """
        client = self._require_client()
        params = {
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        }

        try:
            await asyncio.to_thread(client.utility.verify_payment_signature, params)
        except SignatureVerificationError as exc:
            logger.warning("Signature verification FAILED for order %s", order_id)
            raise RazorpayError(
                "signature_mismatch",
                "Payment signature did not verify. This payment cannot be trusted.",
                details={"order_id": order_id, "payment_id": payment_id},
            ) from exc

        logger.info("Signature verified for order %s payment %s", order_id, payment_id)
        return True

    def verify_webhook_signature(self, body: str, signature: str, secret: str) -> bool:
        """Verify a Razorpay webhook payload signature (sync — no network I/O)."""
        client = self._require_client()
        try:
            client.utility.verify_webhook_signature(body, signature, secret)
        except SignatureVerificationError as exc:
            raise RazorpayError(
                "webhook_signature_mismatch",
                "Webhook signature did not verify; payload rejected.",
            ) from exc
        return True

    # -- plumbing ----------------------------------------------------------

    async def _call(self, fn: Any, *args: Any, action: str) -> dict[str, Any]:
        """Run a blocking SDK call in a thread and normalise its failures."""
        try:
            result = await asyncio.to_thread(fn, *args)
        except BadRequestError as exc:
            # Deterministic — the request itself is wrong. Retrying is pointless.
            raise RazorpayError(
                "provider_rejected",
                f"Razorpay rejected {action}: {exc}",
                details={"action": action},
            ) from exc
        except RETRYABLE_SDK_ERRORS as exc:
            raise RazorpayError(
                "provider_unavailable",
                f"Razorpay {action} failed upstream: {exc}",
                retryable=True,
                details={"action": action},
            ) from exc
        except Exception as exc:  # noqa: BLE001 — network/DNS/TLS and friends
            raise RazorpayError(
                "provider_error",
                f"Razorpay {action} failed: {exc}",
                retryable=True,
                details={"action": action},
            ) from exc

        if not isinstance(result, dict):  # pragma: no cover — SDK contract
            raise RazorpayError(
                "provider_error", f"Unexpected {action} response type: {type(result)!r}"
            )
        return result


_client: RazorpayClient | None = None


def get_razorpay_client() -> RazorpayClient:
    """Process-wide client. Cached because the SDK holds a connection pool."""
    global _client
    if _client is None:
        _client = RazorpayClient()
    return _client
