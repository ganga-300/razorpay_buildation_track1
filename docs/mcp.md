# AutoBuy as an MCP server

The brief asks for an agent-readable catalog and a conversational checkout. This
goes one step further and makes the merchant transactable by **an agent we did
not write**.

That distinction is the whole point. A chat UI wired to your own agent proves
you can build an agent. Exposing the merchant over the Model Context Protocol
proves the *merchant* is transactable — which is what agentic commerce actually
requires, and the shape of Razorpay's own Claude pilot, where Claude discovers
and calls merchant tools directly rather than talking to a bespoke bot.

## The design rule

**Every MCP tool goes through the same `execute_tool` seam the internal agent
uses.** No parallel implementation, no shortcut.

```
 Claude Desktop ──┐
 MCP Inspector ───┤
 any MCP client ──┤
                  ├──> app/mcp/server.py ──┐
 our LangGraph  ──┘                        │
 agent ────────────> app/tools ────────────┴──> services/
                                                  guardrails.py   (caps + gate)
                                                  audit_logger.py (written first)
                                                  idempotency.py  (no double charge)
                                                  orders.py ──> Razorpay (test mode)
```

The guardrails are properties of the **service layer**, not of the caller. An
external MCP client gets exactly the same spend caps, the same approval gate,
the same refusals, and the same audit rows. There is no privilege in arriving
over a different protocol — and `test_mcp_server.py` asserts it.

A drift guard (`test_every_registered_tool_is_exposed_over_mcp`) fails the build
if a tool is added for our agent but not surfaced to everyone else, since that
would quietly re-create the gap this exists to close.

## Tools

| Tool | Moves money | Purpose |
|---|---|---|
| `search_catalog` | no | Search products; also returns the merchant's purchase policy |
| `get_product` | no | One product by id |
| `get_purchase_policy` | no | Current caps and remaining daily headroom |
| `get_order_status` | no | Poll an order's state |
| `create_order` | **yes** | Create a Razorpay order, subject to the guardrails |
| `verify_payment` | **yes** | Verify a signature and settle |

`create_order` deliberately exposes only `product_id`, `quantity`, and an
optional `idempotency_key`:

- **No amount.** The total is computed server-side from the catalog price, so a
  caller cannot choose what the buyer pays.
- **No `conversation_id`.** The server sets it (`mcp-…`), so an external client
  cannot attribute its order to someone else's thread — and the dashboard can
  tell MCP purchases from in-app chat ones.
- **`idempotency_key` is optional and caller-supplied.** Pass the same value to
  retry a call you are unsure completed and the original order comes back rather
  than a second charge. Omit it and each call is a distinct purchase, which is
  the right default when the caller has not said otherwise.

## Running it

```bash
cd backend

# stdio — for Claude Desktop
python -m app.mcp.server

# HTTP — for the MCP Inspector
python -m app.mcp.server --transport streamable-http --port 8765
```

### MCP Inspector

```bash
npx @modelcontextprotocol/inspector
```

Connect to `http://127.0.0.1:8765/mcp` with transport **Streamable HTTP**.

### Claude Desktop

Add to `claude_desktop_config.json`
(`~/Library/Application Support/Claude/` on macOS):

```json
{
  "mcpServers": {
    "autobuy": {
      "command": "/absolute/path/to/backend/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/absolute/path/to/backend"
    }
  }
}
```

Use absolute paths and restart Claude Desktop. The server reads `backend/.env`,
so Razorpay test keys are picked up automatically.

> **stdio speaks JSON-RPC on stdout.** Logging is forced to WARNING on that
> transport — anything printed to stdout corrupts the protocol stream.

## Verified

A cold client importing **only the MCP SDK**, with no application code, over
HTTP:

```
=== an independent MCP client connected over HTTP ===
  server: autobuy v1.1.0

=== discovered 6 tools cold ===
  · search_catalog · get_product · create_order
  · get_order_status · verify_payment · get_purchase_policy

=== it completes a real purchase ===
  found  : prd-usbc-cable-2m at ₹349.00
  ordered: ord-e150d53867be  awaiting_payment  rzp=order_TX3D7GGqvwGkr3

=== the guardrails apply to it exactly as to our own agent ===
  ok=False  code=spend_blocked
  ₹2,499.00 exceeds the per-transaction cap of ₹2,000.00.
```

`order_TX3D7GGqvwGkr3` is a real order on the Razorpay test account, placed by an
agent that shares no code with the AutoBuy chat UI.
