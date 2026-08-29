# AutoBuy — Backend

FastAPI + LangGraph service powering the AutoBuy purchasing agent.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
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

## Endpoints (M0)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Service + dependency status |
| `GET` | `/health/live` | Liveness probe |
| `GET` | `/docs` | OpenAPI UI |

## Tests

```bash
.venv/bin/python -m pytest
```
