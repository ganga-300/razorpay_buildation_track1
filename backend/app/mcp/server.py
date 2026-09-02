"""AutoBuy as an MCP server.

The REST API and the built-in LangGraph agent make this merchant transactable by
*our* agent. This module makes it transactable by *any* agent — Claude Desktop,
the MCP Inspector, or anything else speaking the Model Context Protocol — which
is what "agent-readable catalog" means read strictly.

**Every tool here goes through the same `execute_tool` seam the internal agent
uses.** That is the whole design: the guardrails, the approval gate, the audit
trail and the idempotency keys are properties of the service layer, not of the
caller. An external MCP client gets exactly the same spend caps, the same
refusals, and the same audit rows as the agent we wrote — there is no bypass
just because the request arrived over a different protocol.

Run it:

    # stdio, for Claude Desktop
    python -m app.mcp.server

    # HTTP, for the MCP Inspector
    python -m app.mcp.server --transport streamable-http --port 8765
"""

from __future__ import annotations

import argparse
import json
import logging
import uuid
from typing import Any

from mcp.server.mcpserver import MCPServer

from app.config import settings
from app.db.session import SessionLocal
from app.services.guardrails import budget_snapshot
from app.tools import execute_tool, registry

logger = logging.getLogger(__name__)

# Orders placed over MCP are attributed to this conversation prefix, so the
# dashboard can tell an external agent's purchases from the in-app chat's.
MCP_CONVERSATION_PREFIX = "mcp"

SERVER_INSTRUCTIONS = """\
AutoBuy is a merchant you can buy from on a buyer's behalf, using Razorpay in \
TEST MODE only.

Start with `search_catalog`. Every price is an integer in minor units (paise): \
249900 means Rs 2,499.00. Compare using `amount_minor`; the `display` string is \
for showing a human.

`search_catalog` also returns the merchant's `purchase_policy` — an auto-approve \
limit, a per-transaction cap, and a rolling daily cap. Read it before you try to \
buy. Those limits are enforced server-side and you cannot bypass them:

  - at or below the auto-approve limit, `create_order` completes immediately
  - above it, the order is held at `pending_approval` and a human must approve it
    in the merchant dashboard before anything is charged; nothing is charged
    while it waits
  - above the per-transaction cap, or over the daily cap, the order is refused
    outright and never reaches Razorpay

Being refused is a normal outcome to relay to the buyer, not an error to retry.

Tool results are `{"ok": true, "data": ...}` or `{"ok": false, "error": \
{"code", "message", "retryable"}}`. On failure, tell the buyer what happened in \
plain language. Never present a refusal or a failure as a success.

`create_order` takes no amount — the total is computed server-side from the \
catalog price, so you cannot choose what the buyer pays."""


def _session_conversation_id() -> str:
    """One conversation id per server process, so MCP orders are attributable."""
    return f"{MCP_CONVERSATION_PREFIX}-{uuid.uuid4().hex[:12]}"


CONVERSATION_ID = _session_conversation_id()


async def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run a registered tool in its own database session.

    Returns the envelope untouched — including failures. An MCP client is
    another agent, and it needs the same `{ok, error}` shape our own agent gets
    so it can explain a refusal rather than treat it as a transport fault.
    """
    async with SessionLocal() as session:
        result = await execute_tool(name, session, arguments)

    if not result.get("ok"):
        error = result.get("error") or {}
        logger.info("MCP tool %s refused: %s", name, error.get("code"))
    return result


def build_server() -> MCPServer:
    """Construct the MCP server with every merchant tool registered."""
    server = MCPServer(
        name="autobuy",
        title="AutoBuy — agentic commerce merchant",
        instructions=SERVER_INSTRUCTIONS,
        version="1.1.0",
        website_url="https://razorpay-buildation-track1.vercel.app",
    )

    @server.tool(
        name="search_catalog",
        description=registry.get("search_catalog").description,
    )
    async def search_catalog(
        query: str | None = None,
        category: str | None = None,
        max_price_minor: int | None = None,
        min_price_minor: int | None = None,
        in_stock_only: bool = False,
        limit: int = 10,
    ) -> dict[str, Any]:
        return await _call(
            "search_catalog",
            {
                "query": query,
                "category": category,
                "max_price_minor": max_price_minor,
                "min_price_minor": min_price_minor,
                "in_stock_only": in_stock_only,
                "limit": limit,
            },
        )

    @server.tool(
        name="get_product",
        description=registry.get("get_product").description,
    )
    async def get_product(product_id: str) -> dict[str, Any]:
        return await _call("get_product", {"product_id": product_id})

    @server.tool(
        name="create_order",
        description=registry.get("create_order").description,
    )
    async def create_order(
        product_id: str,
        quantity: int = 1,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create an order, subject to the merchant's spend guardrails.

        `idempotency_key` is optional and caller-supplied: pass the same value
        when retrying a call you are unsure completed, and the original order is
        returned instead of a second charge. Left unset, each call is treated as
        a distinct purchase — two identical calls buy two items, which is the
        correct default when the caller has not told us otherwise.
        """
        return await _call(
            "create_order",
            {
                "product_id": product_id,
                "quantity": quantity,
                # Set by the server, never by the caller: an MCP client must not
                # be able to attribute its order to someone else's conversation.
                "conversation_id": CONVERSATION_ID,
                "idempotency_key": idempotency_key,
            },
        )

    @server.tool(
        name="get_order_status",
        description=registry.get("get_order_status").description,
    )
    async def get_order_status(order_id: str) -> dict[str, Any]:
        return await _call("get_order_status", {"order_id": order_id})

    @server.tool(
        name="verify_payment",
        description=registry.get("verify_payment").description,
    )
    async def verify_payment(
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> dict[str, Any]:
        return await _call(
            "verify_payment",
            {
                "razorpay_order_id": razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_signature": razorpay_signature,
            },
        )

    @server.tool(
        name="get_purchase_policy",
        description=(
            "The merchant's current spend limits and how much of the rolling "
            "daily cap is still available. Check this before proposing a "
            "purchase, so you can tell the buyer up front whether something "
            "will need human approval or be refused outright."
        ),
    )
    async def get_purchase_policy() -> dict[str, Any]:
        async with SessionLocal() as session:
            return {"ok": True, "data": await budget_snapshot(session)}

    return server


mcp_server = build_server()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AutoBuy MCP server.")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "streamable-http", "sse"],
        help="stdio for Claude Desktop; streamable-http for the MCP Inspector.",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    # stdio speaks JSON-RPC on stdout, so logs must never go there.
    logging.basicConfig(level=logging.INFO if args.transport != "stdio" else logging.WARNING)

    logger.info(
        "AutoBuy MCP server: transport=%s razorpay=%s tools=%s",
        args.transport,
        "test mode" if settings.razorpay_configured else "NOT CONFIGURED",
        len(registry.names()) + 1,
    )

    if args.transport == "stdio":
        mcp_server.run("stdio")
    else:
        # In MCP 2.x host/port are run() kwargs, not server settings — assigning
        # them to `.settings` binds the default port and silently ignores --port.
        mcp_server.run(args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
