# AutoBuy

**An AI purchasing agent that makes a merchant transactable end to end — bounded, gated, and fully audited.**

Submission for the Razorpay AI Buildathon, **Track 01 — AI Growth & Agentic Commerce**.

> The judging bar: *every money action explainable, bounded and gated. Show the audit trail and one failure handled gracefully.*

AutoBuy combines two of the track's suggested directions — an **agent-readable catalog** and **conversational in-app checkout**. An AI agent discovers a merchant's products through a machine-readable interface, converses naturally with a buyer, and completes a real purchase through **Razorpay test-mode APIs**, with hard spend limits, human approval above a threshold, and an inspectable audit trail behind every money action.

---

## Architecture at a glance

```
Buyer ──chat──▶ Next.js /chat ──SSE──▶ FastAPI ──▶ LangGraph purchasing agent
                                                          │
                          ┌───────────────────────────────┤
                          ▼                               ▼
                    guardrails.py                   agent tools
                 (spend caps + gating)      search_catalog / get_product
                          │                  create_order / verify_payment
                          ▼                               │
                    audit_logger.py ◀────────────────────┤
                          │                               ▼
                          ▼                     Razorpay API (TEST MODE)
                  AuditLog table ──▶ Next.js /dashboard
```

Every money-moving call passes through `guardrails.py` **before** execution and is written to the audit trail **before and after**.

---

## Repository layout

| Path | What lives there |
|---|---|
| `backend/app/agents/` | LangGraph graph definitions |
| `backend/app/tools/` | Agent tools (catalog search, order creation, payment verification) |
| `backend/app/api/` | FastAPI routers (catalog, chat, orders, webhooks, audit) |
| `backend/app/services/` | Razorpay client, audit logger, guardrails |
| `backend/app/db/` | SQLAlchemy models + async session |
| `backend/app/schemas/` | Pydantic request/response + agent-readable catalog schema |
| `frontend/app/chat/` | Conversational checkout UI |
| `frontend/app/dashboard/` | Merchant audit trail view |
| `frontend/components/` | Reusable UI, chat, and dashboard components |
| `docs/` | Architecture notes and the demo script |

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18.17+
- *(optional)* Docker — for local Postgres + Redis

### 1. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then fill in your Razorpay TEST keys
alembic upgrade head
python -m scripts.seed_catalog     # 9 demo products
uvicorn app.main:app --reload --port 8000
```

Verify: <http://localhost:8000/health> · API docs: <http://localhost:8000/docs>

The backend defaults to **SQLite**, so it boots with zero infrastructure. For Postgres + Redis:

```bash
docker compose up -d
```

then point `DATABASE_URL` and `REDIS_URL` in `backend/.env` at the containers (values are in `.env.example`).

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Verify: <http://localhost:3000>

---

## Razorpay test mode — enforced, not just documented

This project **cannot** be pointed at a live Razorpay account. `backend/app/config.py` validates that `RAZORPAY_KEY_ID` carries the `rzp_test_` prefix and **refuses to start** otherwise. There is a test covering it (`tests/test_config.py`).

Get test keys from the [Razorpay Dashboard](https://dashboard.razorpay.com) → Settings → API Keys, with the dashboard toggled to **Test Mode**.

---

## Tests

```bash
cd backend && .venv/bin/python -m pytest    # 158 tests
```

```bash
cd frontend && npm run test                 # 7 tests
```

---

## Deploy

### Backend → Render

The repo ships a [`render.yaml`](render.yaml) blueprint that provisions the web
service, Postgres, and Redis together.

1. Render Dashboard → **New → Blueprint** → point at this repo.
2. Render prompts for the values marked `sync: false` — they are never committed:

   | Variable | Value |
   |---|---|
   | `RAZORPAY_KEY_ID` | your `rzp_test_...` key |
   | `RAZORPAY_KEY_SECRET` | its secret |
   | `RAZORPAY_WEBHOOK_SECRET` | webhook secret |
   | `ANTHROPIC_API_KEY` | `sk-ant-...` |
   | `CORS_ORIGINS` | the Vercel origin, e.g. `https://autobuy.vercel.app` (no trailing slash) |

3. `DATABASE_URL` and `REDIS_URL` are wired automatically. The Postgres URL
   arrives as `postgresql://...`; `app/config.py` rewrites it to the `asyncpg`
   driver, which is what the async engine needs.

Migrations and the idempotent catalog seed run in the start command, so a
redeploy updates the catalog in place rather than duplicating it.

A [`Dockerfile`](backend/Dockerfile) is included for Fly, Railway, or Cloud Run.

### Frontend → Vercel

1. Import the repo, set **Root Directory** to `frontend`.
2. Set environment variables:

   | Variable | Value |
   |---|---|
   | `NEXT_PUBLIC_API_BASE_URL` | the Render URL, e.g. `https://autobuy-api.onrender.com` |
   | `NEXT_PUBLIC_RAZORPAY_KEY_ID` | the same `rzp_test_...` key id |

3. Deploy, then set `CORS_ORIGINS` on Render to the Vercel origin and redeploy
   the backend. **The two must agree or every request is blocked by CORS.**

### Live URLs

> Fill these in after deploying.

| Surface | URL |
|---|---|
| Frontend | `https://<your-app>.vercel.app` |
| API | `https://<your-api>.onrender.com` |
| API docs | `https://<your-api>.onrender.com/docs` |
| Health | `https://<your-api>.onrender.com/health` |

**Free-tier note:** Render free web services sleep when idle and take ~50s to
wake. Hit `/health` a minute before demoing.

---

## Docs

- [docs/architecture.md](docs/architecture.md) — diagrams, the money path, and why each decision was made
- [docs/demo-script.md](docs/demo-script.md) — the 5-minute walkthrough

---

## The agent-readable catalog

`GET /catalog` returns a **document**, not a bare array. Alongside the products it
carries a schema version, the merchant identity, and — the part that matters for
the judging bar — the **published purchase policy**:

```jsonc
{
  "schema_version": "1.0",
  "spec": "autobuy.catalog/v1",
  "merchant":     { "payment_provider": "razorpay", "payment_mode": "test" },
  "capabilities": {
    "purchase_policy": {
      "auto_approve_limit":      { "amount_minor":   50000, "display": "₹500.00" },
      "per_transaction_cap":     { "amount_minor":  200000, "display": "₹2,000.00" },
      "daily_cap":               { "amount_minor": 1000000, "display": "₹10,000.00" },
      "approval_required_above": { "amount_minor":   50000, "display": "₹500.00" },
      "enforcement": "server-side"
    }
  },
  "products": [ /* ... */ ]
}
```

**Bounds are discoverable, not merely enforced.** A well-behaved agent reads the
policy from the same call that finds products and self-limits before it ever
attempts a purchase. A badly-behaved one still gets stopped server-side by
`services/guardrails.py`. That is what makes a money action *explainable* rather
than just blocked.

Money is always an **integer count of minor units** (paise) plus an explicit
currency. The `display` string is for showing humans — never for parsing.

| Endpoint | Purpose |
|---|---|
| `GET /catalog` | Catalog document. Filters: `q`, `category`, `min_price_minor`, `max_price_minor`, `in_stock_only`, `limit` |
| `GET /catalog/{id}` | One product, same envelope. 404 for unknown or deactivated items |

Search is **AND across tokens** — `q=wireless noise` matches only products
containing both words, so an agent's multi-word query narrows rather than widens.

### Agent tools

`search_catalog` and `get_product` call the same service layer the HTTP routes
use, so the agent and a human browsing the API can never see different results.
Every tool returns a uniform envelope:

```jsonc
{ "ok": true,  "data":  { /* ... */ } }
{ "ok": false, "error": { "code": "product_not_found", "message": "...", "retryable": false } }
```

A tool never raises into the agent loop. A failure becomes something the model can
read and explain to the buyer — the substrate for Milestone 4's graceful failure.

---

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

**Money-moving tools get their own graph nodes.** A generic "execute whatever the
model asked for" node would make the spend gate a conditional buried inside an
executor. Separate nodes make it *structural*: the Milestone 4 guardrail has
exactly one place to live, and the graph refuses to build if a money tool is ever
routed anywhere else.

Four bounds hold no matter what the model does:

| Bound | Enforced by |
|---|---|
| Tool rounds per turn are capped | `AGENT_MAX_ITERATIONS`, checked in the agent node |
| A failing tool degrades the turn, never kills it | uniform `{ok, error}` envelope |
| The model never chooses an amount | totals computed server-side from the catalog |
| An order belongs to its own conversation | `conversation_id` set by the agent, not the model |

That last one matters: if the model supplied `conversation_id`, a prompt
injection could attribute a purchase to someone else's thread. There's a test for it.

Talk to the agent over `POST /chat`, which streams Server-Sent Events —
`conversation`, `intent`, `message`, `tool_call`, `tool_result`, `products`,
`order`, `done`, `error`, `end`. Once the stream has opened, failures arrive as
`error` events rather than status codes.

## Bounded, gated, audited

Every money action runs the same sequence, and the ordering is load-bearing:

```
1. validate the product, compute the amount locally
2. reserve the idempotency key
3. guardrails.evaluate()  ->  allow | require_approval | block
4. write the audit entry  <-  BEFORE anything irreversible
5. persist the local Order row
6. only now call Razorpay, retrying once on a retryable failure
7. update the order AND the audit entry with what happened
```

**Step 4 is why a refusal is as well-recorded as a success.** An audit trail
written *after* the fact has no record of the most dangerous case — the process
dying mid-charge. Writing first inverts that: an entry left `pending` is itself
the finding.

### The three verdicts

| Amount | Verdict | What happens |
|---|---|---|
| ≤ ₹500 | `allow` | executes immediately |
| ₹500 – ₹2,000 | `require_approval` | order held at `pending_approval`, nothing charged, human must click Approve |
| > ₹2,000 | `block` | refused outright; Razorpay is never contacted |

**Hard caps are checked before the approval threshold.** If the order were
reversed, a buyer could be prompted to authorise an amount the merchant has
forbidden — and a cap a human can click through is not a cap.

**Approval is a POST to `/orders/{id}/approve`, never the model reading "yes".**
A confirmation inferred from chat text is one a prompt injection can forge. Caps
are also re-evaluated at approval time: an approval is permission for an amount,
not a bypass of the daily cap.

### One failure, handled gracefully

A retryable provider failure is retried **once** with backoff, then gives up.
Deliberately once — a gateway that is failing rarely recovers in milliseconds,
and every extra attempt widens the window for a double charge. A deterministic
rejection is not retried at all.

What the buyer sees: *"The payment provider timed out. I retried once with a
backoff and it failed again, so I stopped rather than risk a double charge.
Nothing was charged and the order is recorded as failed."*

What the trail records:

```
aud-250f6c4c2f78  create_order  ₹1,799.00
  decision=require_approval -> outcome=failed   attempts=2   by=buyer
  failure: provider_unavailable — Razorpay gateway timed out
    [ok  ] per_transaction_cap    ₹1,799.00 / ₹2,000.00
    [ok  ] daily_cap              ₹3,098.00 / ₹10,000.00
    [FAIL] auto_approve_limit     ₹1,799.00 / ₹500.00
```

`attempts=2` is the retry. The bounds are **snapshotted at decision time**, not
recomputed, so the record stays truthful after the configured caps change.

### No double charges

Three overlapping layers, because one is not enough:

1. **Redis** reserves the key before the provider call, so a concurrent retry is
   refused rather than racing. Falls back to an in-process store when `REDIS_URL`
   is unset — correct for one worker.
2. **A unique index** on `orders.idempotency_key`, which holds even if Redis is
   flushed or unavailable.
3. **A replay lookup** so a repeat returns the original order instead of an error.

The key is derived from the model's own `tool_use` id, so an internal retry of
one call reuses it while a genuine second purchase gets a new one.

### The interface

`/chat` renders **every tool the agent calls inline** — name, arguments, outcome —
with money-moving calls badged *moves money*. A purchasing agent whose actions
are invisible is not one anybody should trust with a card. Products and orders
arrive as structured events and render as cards, not as text the model wrote.

`/dashboard` lists every order the agent created, **including the ones that
failed**, with the failure code and reason against each. Settled and awaiting-
payment totals are reported separately: an order awaiting payment is intent, not
spend, and adding them together would overstate what the agent has done.

Payment verification posts to `/payments/verify` rather than routing back through
the agent — a signature check is a security control, and a control that only runs
if a language model decides to call a tool is not a control.

### Model

Claude `claude-opus-5` via the official `anthropic` SDK with adaptive thinking.
LangGraph owns the state machine; it does not own the model call. `langchain-anthropic`
is deliberately not a dependency — one less wrapper between this code and the API.

---

## Milestone status

- [x] **M0** — Scaffold, env config, health checks
- [x] **M1** — Agent-readable catalog + search/get tools
- [x] **M2** — LangGraph purchasing agent + Razorpay order/verify tools
- [x] **M3** — Conversational checkout UI + merchant dashboard
- [x] **M4** — Spend caps, approval gating, audit trail, graceful failure
- [ ] **M5** — Deploy + demo assets
