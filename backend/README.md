# AutoBuy — Backend

FastAPI + LangGraph service powering the AutoBuy purchasing agent.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python -m scripts.seed_catalog
uvicorn app.main:app --reload --port 8000
```

## Layout

```
app/
├── agents/      LangGraph graph definitions
├── tools/       Agent-callable tools
├── api/         FastAPI routers
├── services/    razorpay_client · audit_logger · guardrails
├── db/          base (declarative) · session (async engine) · models
├── schemas/     Pydantic request/response models
├── config.py    Typed settings — the only place env vars are read
└── main.py      App factory + lifespan
```

## Design rules

1. **Test mode is enforced at startup.** `config.py` rejects any `RAZORPAY_KEY_ID`
   without the `rzp_test_` prefix.
2. **Config is read in exactly one place** — `app/config.py`. Nothing else calls
   `os.environ`.
3. **Every money-moving function** goes through `services/guardrails.py` first and
   writes to `services/audit_logger.py` before *and* after execution.
4. **Migrations read `DATABASE_URL` from `app.config`**, not from `alembic.ini`, so
   the app and its schema can never drift.

## Database

Defaults to SQLite (`sqlite+aiosqlite`) so the service boots with no infrastructure.
Set `DATABASE_URL` to a `postgresql+asyncpg://` URL for Postgres — `render.yaml` and
`docker-compose.yml` both do this.

```bash
alembic revision --autogenerate -m "add products"
alembic upgrade head
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Service + dependency status |
| `GET` | `/health/live` | Liveness probe |
| `GET` | `/catalog` | Agent-readable catalog document |
| `GET` | `/catalog/{id}` | Single product |
| `POST` | `/chat` | Conversational checkout (Server-Sent Events) |
| `GET` | `/docs` | OpenAPI UI |

### `POST /chat` event stream

Body: `{"message": "...", "conversation_id": "conv-..."}` — omit the id to start
a thread; it comes back in the first event.

| Event | Payload |
|---|---|
| `conversation` | `{conversation_id}` — always first |
| `intent` | `{intent}` — browse / purchase / verify / cancel / other |
| `message` | `{text}` — agent prose |
| `tool_call` | `{tool, arguments, mutates_money}` |
| `tool_result` | `{tool, ok, error}` |
| `products` | `{products: [...]}` — render as cards |
| `order` | `{order: {...}}` — render as an order card |
| `done` | `{text, intent}` |
| `error` | `{code, message, retryable}` |
| `end` | `{conversation_id}` — always last |

Errors after the stream opens arrive as `error` events, not status codes — once
the response has begun there is no status left to change.

### Catalog filters

`q` (AND across whitespace tokens) · `category` (case-insensitive) ·
`min_price_minor` · `max_price_minor` · `in_stock_only` · `limit` (max 100).

## Seeding

```bash
python -m scripts.seed_catalog          # insert or update
python -m scripts.seed_catalog --reset  # wipe products first
```

Nine products spanning every guardrail band, so the Milestone 4 demo can show all
three outcomes with real catalog items:

| Band | Price range | Demo outcome | Example |
|---|---|---|---|
| A | ≤ ₹500 | auto-approves | `prd-usbc-cable-2m` ₹349 |
| B | ₹500 – ₹2,000 | hits the approval gate | `prd-wireless-mouse` ₹1,299 |
| C | > ₹2,000 | refused by the per-transaction cap | `prd-anc-headphones` ₹2,499 |

`prd-espresso-machine` is intentionally out of stock so `in_stock_only` has
something to filter.

## Agent tools

Tools live in `app/tools/` and self-register on import of the package.

| Tool | Moves money | Purpose |
|---|---|---|
| `search_catalog` | no | Search products; also returns the purchase policy |
| `get_product` | no | Fetch one product by id |
| `create_order` | **yes** | Create a Razorpay order (test mode) |
| `verify_payment` | **yes** | Verify a payment signature and settle the order |

Two invariants hold for every tool:

- **Uniform envelope.** `{"ok": true, "data": ...}` or
  `{"ok": false, "error": {"code", "message", "retryable"}}`. `execute_tool`
  converts every exception into an envelope, so a tool failure can never kill an
  agent turn.
- **Declared money-mutation.** `ToolSpec.mutates_money` marks the tools that must
  pass `services/guardrails.py` and be audited. The executor reads that flag, so a
  new money tool cannot be added and quietly skip the gate.

Tools call `services/catalog.py` directly rather than issuing HTTP requests back
into the same process — identical payloads to the `/catalog` routes, without a
pointless network hop.

## Tests

```bash
.venv/bin/python -m pytest
```


## The purchasing agent

```
START -> parse_intent -> agent -> [dispatch] -> search_catalog
                          ^                  -> create_order      (money)
                          |                  -> verify_payment    (money)
                          |                        |
                          +---- collect_results <--+
                          |
                          +-> finish -> END
```

**Money tools get their own nodes.** That is the design, not an accident. A
generic "run whatever the model asked for" node would make the spend gate a
conditional buried in an executor; separate nodes make it structural, so the
Milestone 4 guardrail has exactly one place to live and cannot be bypassed by a
tool being routed elsewhere. `_validate_tool_coverage()` fails at import if a
money tool is ever routed to a non-gated node, and a test asserts it.

Bounds that hold regardless of what the model does:

- `AGENT_MAX_ITERATIONS` caps tool rounds per turn — a looping model terminates.
- Every tool result is an envelope, so one failing tool degrades the answer
  rather than killing the turn.
- `create_order`'s `conversation_id` is set by the agent, never by the model — a
  prompt injection cannot attribute an order to someone else's thread.
- The model never passes an amount. Totals are computed server-side from the
  catalog price.

### Model

Claude `claude-opus-5` through the official `anthropic` SDK, with adaptive
thinking. LangGraph owns the state machine; it does not own the model call.
`langchain-anthropic` is deliberately not a dependency — one less wrapper
between this code and the API.

Thinking blocks are persisted verbatim with the transcript (signature included)
because Claude requires them echoed back unchanged when a conversation continues
on the same model, and the transcript round-trips through the database between
HTTP requests.

## Order lifecycle

`pending_approval` (M4) -> `created` -> `awaiting_payment` -> `paid`
                                    \-> `failed` / `cancelled` / `blocked` (M4)

The local order row is written **before** the Razorpay call, so a provider
failure still leaves a durable record that the agent intended to charge, with
the failure recorded against it. An order that existed only inside a failed HTTP
call would be invisible to an auditor.

Stock is decremented only when payment verifies, so an abandoned checkout never
silently consumes inventory. Re-verification is idempotent, because Razorpay can
deliver both a checkout callback and a webhook for the same payment.
