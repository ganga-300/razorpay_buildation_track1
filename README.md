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
cd backend && .venv/bin/python -m pytest
```

---

## Milestone status

- [x] **M0** — Scaffold, env config, health checks
- [ ] **M1** — Agent-readable catalog
- [ ] **M2** — LangGraph purchasing agent
- [ ] **M3** — Chat UI + merchant dashboard
- [ ] **M4** — Guardrails, audit trail, graceful failure
- [ ] **M5** — Deploy + demo assets
