#!/usr/bin/env python3
"""An independent AI buyer that transacts with AutoBuy over MCP.

This file is the evidence for the interoperability claim, so read what it
imports: `asyncio`, `argparse`, and the Model Context Protocol SDK. Nothing
else. It cannot import AutoBuy — it does not live in that package, and the
environment it runs in (`demo/.venv`) has only the MCP SDK installed.

It is a stand-in for Claude Desktop or the MCP Inspector: a buyer-side agent
that has never seen the merchant's source, discovering the catalog cold and
completing a real purchase through Razorpay test mode.

The part that matters is not that the purchase succeeds. It is that the
merchant's spend guardrails refuse this client exactly as they refuse the
merchant's own agent — because those limits live in the merchant's service
layer, not in whichever client happens to be calling.

    python demo/mcp_buyer.py --url http://127.0.0.1:8765/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

PACE = 0.9  # deliberate pauses, so the output is readable on video

RULE = "─" * 66


def say(text: str = "") -> None:
    print(text, flush=True)


async def beat(text: str = "") -> None:
    """Print, then pause — the demo is meant to be watched, not scrolled."""
    say(text)
    await asyncio.sleep(PACE)


async def heading(text: str) -> None:
    say()
    say(RULE)
    say(f"  {text}")
    say(RULE)
    await asyncio.sleep(PACE)


def envelope(result) -> dict:  # type: ignore[no-untyped-def]
    """Every AutoBuy tool answers `{ok, data}` or `{ok, error}`."""
    return result.structured_content or {}


async def run(url: str) -> int:
    await heading("An independent agent connects to a merchant it has never seen")
    await beat(f"  transport : streamable HTTP")
    await beat(f"  endpoint  : {url}")
    await beat("  imports   : mcp SDK only — no AutoBuy code on this side")

    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            await beat(
                f"\n  connected to '{init.server_info.name}' v{init.server_info.version}"
            )

            # ---- discovery -------------------------------------------------
            await heading("It discovers what the merchant can do")
            tools = (await session.list_tools()).tools
            for tool in tools:
                await beat(f"  · {tool.name}")

            # ---- the rules, before spending anything -----------------------
            await heading("It reads the merchant's spend policy before buying")
            policy = envelope(await session.call_tool("get_purchase_policy", {}))["data"]
            await beat(f"  auto-approve limit   {policy['auto_approve_limit']['display']:>12}")
            await beat(f"  per-transaction cap  {policy['per_transaction_cap']['display']:>12}")
            await beat(f"  daily cap            {policy['cap']['display']:>12}")
            await beat(f"  already spent today  {policy['spent']['display']:>12}")

            # ---- browse ----------------------------------------------------
            await heading("It searches the catalog")
            found = envelope(
                await session.call_tool("search_catalog", {"query": "cable", "limit": 3})
            )
            products = found["data"]["products"]
            for product in products:
                await beat(f"  {product['id']:<26} {product['price']['display']:>10}")

            if not products:
                say("\n  Nothing in the catalog — is the merchant seeded?")
                return 1

            # ---- buy -------------------------------------------------------
            target = products[0]
            await heading(f"It buys the {target['name']}")
            result = envelope(
                await session.call_tool("create_order", {"product_id": target["id"]})
            )

            if not result.get("ok"):
                error = result["error"]
                await beat(f"  refused: {error['code']}")
                await beat(f"  {error['message']}")
                if error["code"] == "spend_blocked":
                    await beat(
                        "\n  The merchant refused this client the same way it would"
                    )
                    await beat("  refuse its own agent. That is the point.")
                return 0

            order = result["data"]
            await beat(f"  order    : {order['order_id']}")
            await beat(f"  total    : {order['total']['display']}")
            await beat(f"  status   : {order['status']}")
            await beat(f"  razorpay : {order['razorpay_order_id']}")
            await beat("\n  That is a real order on the merchant's Razorpay test account,")
            await beat("  placed by an agent that shares no code with their app.")

            # ---- the guardrails apply here too -----------------------------
            await heading("The merchant's limits bind this client too")
            expensive = envelope(
                await session.call_tool(
                    "create_order", {"product_id": "prd-anc-headphones"}
                )
            )
            if expensive.get("ok"):
                await beat("  (unexpectedly allowed — check the configured caps)")
            else:
                error = expensive["error"]
                await beat(f"  attempted: Wireless Noise Cancelling Headphones")
                await beat(f"  refused  : {error['code']}")
                await beat(f"\n  {error['message']}")

                guardrail = (error.get("details") or {}).get("guardrail")
                if guardrail:
                    await beat("\n  Bounds the merchant checked:")
                    for check in guardrail["checks"]:
                        mark = "ok  " if check["passed"] else "FAIL"
                        say(
                            f"    [{mark}] {check['name']:<22}"
                            f"{check['observed_display']:>11} / {check['limit_display']}"
                        )
                    await asyncio.sleep(PACE)

            say()
            say(RULE)
            await beat("  Same merchant. Different agent. Same guardrails.")
            say(RULE)
            say()

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="An independent MCP client that buys from AutoBuy."
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8765/mcp",
        help="The merchant's MCP endpoint.",
    )
    parser.add_argument(
        "--fast", action="store_true", help="No pauses (for scripted checks, not video)."
    )
    args = parser.parse_args()

    if args.fast:
        global PACE
        PACE = 0

    try:
        sys.exit(asyncio.run(run(args.url)))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001 — a demo must fail legibly
        say(f"\n  Could not complete: {type(exc).__name__}: {exc}")
        say("  Is the MCP server running?")
        say("    cd backend && python -m app.mcp.server --transport streamable-http --port 8765")
        sys.exit(1)


if __name__ == "__main__":
    main()
