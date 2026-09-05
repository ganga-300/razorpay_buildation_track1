"""A deterministic planner that satisfies the `LLMClient` protocol.

Why this exists: an Anthropic key needs a funded account, and the demo should
not be undemoable without one. Everything the judging bar cares about —
guardrails, the approval gate, the audit trail, retry, idempotency — is enforced
server-side and does not involve the model at all. Swapping the brain therefore
leaves the entire money path real, including live Razorpay test-mode calls.

That is the point worth making out loud: **the safety properties do not depend
on the language model behaving.** This planner is the proof. It is deliberately
dumb — keyword rules over the catalog the tools return — and every cap, gate,
and audit row still holds exactly as it does with Claude driving.

It is **not** a simulation of Claude and must never be presented as one. It is
selected only by `AGENT_MODE=scripted`, it is not the default, and the UI badges
every turn it produces.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from app.agents.llm import LLMResponse, extract_text, extract_tool_calls

logger = logging.getLogger(__name__)

# Matched on WORD BOUNDARIES, never as substrings. "noise cancelling headphones"
# contains "cancel", and a naive substring check turns a browse into a
# cancellation — the agent replying "I won't order anything" to someone asking
# to see headphones.
PURCHASE_WORDS = {"buy", "order", "purchase", "yes", "approve", "confirm", "get me"}
VERIFY_WORDS = {"paid", "payment done", "verify", "completed payment"}
# "did it work", "what happened to my order" — a status question, not a purchase.
STATUS_WORDS = {
    "status", "did it work", "go through", "went through", "confirmed",
    "what happened", "any update", "is it done",
}
CANCEL_WORDS = {"cancel", "cancelled", "no thanks", "never mind", "stop", "forget it"}

# Words that mean the buyer is still looking. Checked against the RAW message,
# before stopword removal, so that naming a product the agent just listed can be
# told apart from asking to see more of them.
BROWSE_WORDS = {
    "show", "find", "search", "see", "browse", "look", "looking", "what",
    "which", "any", "anything", "else", "other", "others", "options",
    "alternative", "alternatives", "cheaper", "instead", "compare",
}

# Words that carry no signal when matching a request to a product. Catalog
# search is AND across tokens, so a single conversational word like "show"
# reduces a good query to zero results.
STOPWORDS = {
    # conversational filler
    "a", "again", "an", "and", "another", "any", "anything", "are", "buy",
    "can", "could", "do",
    "find", "for", "get", "got", "have", "hey", "hi", "i", "in", "is", "it",
    "more", "one",
    "like", "look", "looking", "me", "my", "need", "of", "on", "one", "or",
    "order", "please", "purchase", "recommend", "search", "see", "show",
    "similar", "some", "something", "suggest", "that", "the", "then", "there",
    "this",
    "to", "want", "what", "which", "with", "would", "you", "your",
    # budget phrasing — already captured by _price_ceiling, and useless in a
    # query where every token must match
    "below", "budget", "cheap", "cheaper", "inr", "less", "max", "maximum",
    "rs", "than", "under", "up", "upto", "within",
}

# Catalog search requires EVERY token to match, so the query is kept tight:
# at most this many tokens, longest first, single characters dropped. Dumping
# every keyword in ("c cable show usb") reliably matches nothing.
MAX_QUERY_TOKENS = 2


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _tool_block(call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": args}


def _respond(*blocks: dict[str, Any]) -> LLMResponse:
    content = list(blocks)
    calls = extract_tool_calls(content)
    return LLMResponse(
        text=extract_text(content),
        tool_calls=calls,
        stop_reason="tool_use" if calls else "end_turn",
        content=content,
    )


def _mentions(text: str, phrases: set[str]) -> bool:
    """True if any phrase appears as a whole word or whole phrase.

    Case-folds internally, so callers can pass the original message and keep
    case-sensitive content (Razorpay ids) intact.
    """
    lowered = text.lower()
    return any(
        re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered) for phrase in phrases
    )


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    """The buyer's most recent message, in its ORIGINAL case.

    It used to be lowercased here for keyword matching, which silently corrupted
    the one thing in a chat message that is case-sensitive: Razorpay
    identifiers. `order_TESTFAKE0001` became `order_testfake0001` and every
    pasted verification failed with order_not_found.

    Case folding now happens where matching needs it, never on the way in.
    """
    for m in reversed(messages):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            return m["content"]
    return ""


def _last_tool_result(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The most recent tool result envelope, decoded."""
    tail = messages[-1] if messages else None
    if not tail or not isinstance(tail.get("content"), list):
        return None
    for block in tail["content"]:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            try:
                return json.loads(block.get("content") or "{}")
            except (ValueError, TypeError):
                return None
    return None


def _products_seen(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every product surfaced anywhere in this conversation.

    Lets "buy the mouse" resolve against something already shown, instead of
    searching again and risking a different match than the buyer saw.
    """
    found: dict[str, dict[str, Any]] = {}
    for m in messages:
        if not isinstance(m.get("content"), list):
            continue
        for block in m["content"]:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            try:
                payload = json.loads(block.get("content") or "{}")
            except (ValueError, TypeError):
                continue
            data = payload.get("data") or {}
            for p in data.get("products") or []:
                if isinstance(p, dict) and p.get("id"):
                    found[p["id"]] = p
            if isinstance(data.get("product"), dict) and data["product"].get("id"):
                found[data["product"]["id"]] = data["product"]
    return list(found.values())


def _orders_seen(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every order this conversation has produced, oldest first.

    Lets "did my payment go through?" resolve against the order the buyer is
    actually asking about, without them having to quote an id back at us.
    """
    found: dict[str, dict[str, Any]] = {}
    for message in messages:
        if not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            try:
                payload = json.loads(block.get("content") or "{}")
            except (ValueError, TypeError):
                continue
            data = payload.get("data") or {}
            if data.get("order_id"):
                found[data["order_id"]] = data
            inner = data.get("order")
            if isinstance(inner, dict) and inner.get("order_id"):
                found[inner["order_id"]] = inner
    return list(found.values())


# Razorpay identifiers a buyer might paste back after paying. The signature is
# a 64-character HMAC-SHA256 hex digest.
_RZP_ORDER = re.compile(r"\border_[A-Za-z0-9]{8,}\b")
_RZP_PAYMENT = re.compile(r"\bpay_[A-Za-z0-9]{8,}\b")
_RZP_SIGNATURE = re.compile(r"\b[a-f0-9]{64}\b")


def _checkout_values(text: str) -> dict[str, str] | None:
    """Pull a full set of Razorpay checkout values out of a chat message.

    All three or nothing: verifying with a missing field is not a partial
    verification, it is a failed one, and failing it here wastes a round trip to
    tell the buyer something we can already see.
    """
    order = _RZP_ORDER.search(text)
    payment = _RZP_PAYMENT.search(text)
    signature = _RZP_SIGNATURE.search(text)
    if not (order and payment and signature):
        return None
    return {
        "razorpay_order_id": order.group(0),
        "razorpay_payment_id": payment.group(0),
        "razorpay_signature": signature.group(0),
    }


# An exact catalog id the buyer named, e.g. "get me prd-wireless-mouse".
_PRODUCT_ID = re.compile(r"\bprd-[a-z0-9-]{3,}\b", re.I)


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS}


def _query_from(text: str) -> str:
    """Build a tight catalog query: longest distinctive tokens, no fragments.

    Single characters are dropped — "usb-c" tokenises to {"usb", "c"}, and the
    stray "c" would AND the query down to nothing.
    """
    # Pure digits are dropped: "under 500" already became a price filter, and
    # requiring "500" to appear in the product text matches nothing. Mixed
    # tokens like "2m" or "100w" are kept — those are real product words.
    tokens = [w for w in _keywords(text) if len(w) > 1 and not w.isdigit()]
    tokens.sort(key=lambda w: (-len(w), w))
    return " ".join(tokens[:MAX_QUERY_TOKENS])


def _best_match(text: str, products: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Highest keyword overlap between the request and a product."""
    wanted = _keywords(text)
    if not wanted:
        return None

    best, best_score = None, 0
    for p in products:
        haystack = f"{p.get('name', '')} {p.get('category', '')} {p.get('id', '')}"
        score = len(wanted & _keywords(haystack))
        if score > best_score:
            best, best_score = p, score
    return best if best_score > 0 else None


# "under 2000", "below Rs 1,299", "less than ₹500"
_CEILING_BEFORE = re.compile(
    r"(?:under|below|less than|max|maximum|upto|up to|within)\s*"
    r"(?:rs\.?|₹|inr)?\s*([\d,]+)"
)
# "₹500 max", "rs 2000 or less" — the qualifier trails the amount.
_CEILING_AFTER = re.compile(
    r"(?:rs\.?|₹|inr)\s*([\d,]+)\s*(?:max|maximum|or less|or under|budget)?"
)


def _price_ceiling(text: str) -> int | None:
    """Pull a rupee ceiling out of natural phrasing, in minor units.

    A bare number is deliberately NOT treated as a budget — "2 metre cable"
    would otherwise become a ₹2 ceiling and match nothing.
    """
    lowered = text.lower()
    for pattern in (_CEILING_BEFORE, _CEILING_AFTER):
        m = pattern.search(lowered)
        if m:
            try:
                return int(m.group(1).replace(",", "")) * 100
            except ValueError:
                continue
    return None


class ScriptedPlanner:
    """Rule-based stand-in for the model. Same protocol, no network, no spend."""

    is_scripted = True

    def __init__(self) -> None:
        self.model = "scripted-planner"
        self._counter = 0

    @property
    def configured(self) -> bool:
        return True

    def _next_id(self) -> str:
        self._counter += 1
        return f"scripted-{self._counter}"

    # -- intent ------------------------------------------------------------

    def _classify(self, text: str) -> str:
        if _mentions(text, CANCEL_WORDS):
            return "cancel"
        if _mentions(text, VERIFY_WORDS):
            return "verify"
        if _mentions(text, PURCHASE_WORDS):
            return "purchase"
        return "browse"

    # -- replies to tool results -------------------------------------------

    def _reply_to_result(
        self, envelope: dict[str, Any], user_text: str = ""
    ) -> LLMResponse:
        if not envelope.get("ok"):
            error = envelope.get("error") or {}
            code = error.get("code", "")
            message = error.get("message", "Something went wrong.")

            if code == "spend_blocked":
                # The guardrail reason is already a complete explanation; adding
                # a second one just repeats it back at the buyer.
                return _respond(_text_block(
                    f"I can't place that order. {message} "
                    "Tell me a lower budget and I'll find something that fits."
                ))
            if code == "insufficient_stock":
                return _respond(_text_block(f"{message} Want me to look for an alternative?"))
            if code in {"provider_unavailable", "provider_error"}:
                return _respond(_text_block(
                    f"The payment provider failed: {message} I retried once with a "
                    "backoff and stopped rather than risk a double charge. Nothing "
                    "was charged. Try again in a moment."
                ))
            if code == "signature_mismatch":
                return _respond(_text_block(
                    f"{message} I've marked the order failed rather than treat an "
                    "unverifiable payment as successful."
                ))
            return _respond(_text_block(f"That didn't work: {message}"))

        data = envelope.get("data") or {}

        if data.get("approval_required"):
            total = (data.get("total") or {}).get("display", "that amount")
            return _respond(_text_block(
                f"{total} is above my auto-approve limit, so I've held the order and "
                "need your explicit approval before anything is charged. The exact "
                "limits I checked are shown above."
            ))

        # get_order_status wraps the order one level deeper.
        inner = data.get("order")
        if isinstance(inner, dict) and inner.get("order_id"):
            status = inner["status"]
            total = (inner.get("total") or {}).get("display", "")
            phrasing = {
                "paid": f"That order is settled — {total} paid and confirmed.",
                "awaiting_payment": (
                    f"That order is still awaiting payment. {total} is reserved but "
                    "nothing has been charged yet — complete the payment to finish."
                ),
                "pending_approval": (
                    f"That order is still waiting on your approval. {total} won't be "
                    "charged until you approve it."
                ),
                "failed": "That order failed. "
                + ((inner.get("failure") or {}).get("reason") or "No payment was taken."),
                "blocked": "That order was blocked by a spend guardrail, so nothing was charged.",
                "cancelled": "That order was cancelled. Nothing was charged.",
            }
            return _respond(_text_block(
                phrasing.get(status, f"That order is currently '{status}'.")
            ))

        if data.get("order_id") and data.get("status") == "paid":
            return _respond(_text_block(
                f"Payment verified. Order {data['order_id']} is settled."
            ))

        if data.get("order_id"):
            total = (data.get("total") or {}).get("display", "")
            return _respond(_text_block(
                f"Order created for {total}. Complete the payment to finish — "
                "I'll confirm once the signature verifies."
            ))

        products = data.get("products") or []
        if products:
            # The buyer already said "buy", and this search only happened because
            # nothing had been shown yet. Listing the result back and waiting for
            # a second "buy" would be pointless ceremony.
            if self._classify(user_text) == "purchase":
                in_stock = [
                    p for p in products if (p.get("availability") or {}).get("in_stock")
                ]
                if in_stock:
                    return _respond(
                        _text_block(
                            f"Ordering the {in_stock[0]['name']}. "
                            "Checking the spend limits first."
                        ),
                        _tool_block(
                            self._next_id(),
                            "create_order",
                            {"product_id": in_stock[0]["id"], "quantity": 1},
                        ),
                    )

            lines = [
                f"· {p['name']} — {p['price']['display']}"
                f"{'' if p['availability']['in_stock'] else '  (out of stock)'}"
                for p in products[:3]
            ]
            body = "\n".join(lines)
            return _respond(_text_block(
                f"Here's what matches:\n\n{body}\n\n"
                "Tell me which one to order and I'll check the spend limits."
            ))

        return _respond(_text_block(
            "I couldn't find anything matching that. Try describing it differently."
        ))

    # -- the protocol -------------------------------------------------------

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
        model: str | None = None,
        purpose: str = "agent",
    ) -> LLMResponse:
        # model/purpose are part of the LLMClient protocol (they route real
        # API calls to a cheaper model and tag them for cost accounting — see
        # AnthropicLLMClient). The planner never calls an API, so there is
        # nothing to route and nothing to spend; both are accepted and ignored
        # so it satisfies the same interface Claude does.
        text = _latest_user_text(messages)

        # No tools bound => the intent-classification call.
        if not tools:
            return _respond(_text_block(self._classify(text)))

        # Just received a tool result => produce the buyer-facing reply.
        result = _last_tool_result(messages)
        if result is not None:
            return self._reply_to_result(result, user_text=text)

        intent = self._classify(text)

        # The buyer pasted the values Razorpay Checkout handed back. This is the
        # one case where settling through chat makes sense; the browser callback
        # posts to /payments/verify directly and does not need the agent.
        checkout = _checkout_values(text)
        if checkout:
            return _respond(
                _text_block("Verifying that payment signature."),
                _tool_block(self._next_id(), "verify_payment", checkout),
            )

        # "Did my payment go through?" — answerable from the order we created,
        # without asking the buyer to quote an id back at us.
        if intent == "verify" or _mentions(text, STATUS_WORDS):
            orders = _orders_seen(messages)
            if orders:
                return _respond(
                    _text_block("Let me check that order."),
                    _tool_block(
                        self._next_id(),
                        "get_order_status",
                        {"order_id": orders[-1]["order_id"]},
                    ),
                )
            return _respond(_text_block(
                "I haven't placed an order in this conversation yet, so there's "
                "nothing to check. Tell me what you'd like to buy."
            ))

        # The buyer named an exact catalog id — fetch it directly rather than
        # guessing at it through search.
        exact = _PRODUCT_ID.search(text)
        if exact and intent != "purchase":
            return _respond(
                _text_block("Looking that up."),
                _tool_block(
                    self._next_id(), "get_product", {"product_id": exact.group(0).lower()}
                ),
            )

        if intent == "cancel":
            return _respond(_text_block(
                "Understood — I won't order anything. Nothing has been charged."
            ))

        # The agent just listed products and asked which one to order. Answering
        # with the product's name is the natural reply, and it carries no verb —
        # so intent alone reads it as "browse" and the agent searches again,
        # relists the same item, and asks the same question. That loop is what a
        # buyer actually hits first.
        if intent == "browse" and not _mentions(text, BROWSE_WORDS):
            named = _best_match(text, _products_seen(messages))
            if named is not None:
                intent = "purchase"

        if intent == "purchase":
            if exact:
                return _respond(
                    _text_block("Checking the spend limits first."),
                    _tool_block(
                        self._next_id(),
                        "create_order",
                        {"product_id": exact.group(0).lower(), "quantity": 1},
                    ),
                )
            match = _best_match(text, _products_seen(messages))
            if match:
                return _respond(
                    _text_block("Checking the spend limits first."),
                    _tool_block(self._next_id(), "create_order",
                                {"product_id": match["id"], "quantity": 1}),
                )
            # Nothing shown yet that matches — search, then buy on the next turn.

        args: dict[str, Any] = {"limit": 3}
        query = _query_from(text)
        if query:
            args["query"] = query
        ceiling = _price_ceiling(text)
        if ceiling:
            args["max_price_minor"] = ceiling

        return _respond(
            _text_block("Let me check the catalog."),
            _tool_block(self._next_id(), "search_catalog", args),
        )

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
        model: str | None = None,
        purpose: str = "agent",
    ) -> AsyncIterator[tuple[str, Any]]:
        result = await self.complete(
            system=system, messages=messages, tools=tools,
            max_tokens=max_tokens, effort=effort,
            model=model, purpose=purpose,
        )
        if result.text:
            yield ("text", result.text)
        yield ("final", result)
