# The two clips

Two short screen recordings carry the differentiation. A panel watches a
five-minute video once, so each is scripted to make exactly **one** point, and
each is rehearsable from a clean state.

| Clip | Runtime | The one point |
|---|---|---|
| 1 · Interoperability | ~60s | An agent **we did not write** can transact with this merchant, and the same guardrails bind it |
| 2 · Revocation | ~75s | Purchasing authority can be **withdrawn instantly**, and the very next order fails |

Record them separately. Do not narrate over dead air while something loads —
reset first, then hit record.

---

## Before either clip

```bash
cd backend && python -m uvicorn app.main:app --port 8000        # terminal 1
cd frontend && npm run dev                                       # terminal 2
```

Point `frontend/.env.local` at **`http://localhost:8000`** while recording
locally. If it points at the deployed Render URL, the browser is talking to
production and CORS will block it — the symptom is a chat that hangs silently,
which looks nothing like the cause.

Set `AGENT_MODE=scripted` unless the Anthropic account is funded.

---

## Clip 1 — An agent we did not write

**Setup** (before recording):

```bash
python demo/reset.py --granted
cd backend && python -m app.mcp.server --transport streamable-http --port 8765
```

**On camera**, show these three things in order:

**1. The client is genuinely independent** — 10 seconds, and it is the whole
claim. Open `demo/mcp_buyer.py` and show the imports:

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
```

Then, in the terminal:

```bash
demo/.venv/bin/python -c "import app"
# ModuleNotFoundError: No module named 'app'
```

> "This client runs in its own environment. It cannot import the merchant's
> code — that module doesn't exist here. It only has the MCP SDK."

**2. Run it:**

```bash
demo/.venv/bin/python demo/mcp_buyer.py
```

It connects, discovers six tools cold, reads the merchant's spend policy, and
buys — printing a real Razorpay order id.

> "It has never seen this merchant. It discovers what's available, reads the
> spend policy the merchant publishes, and buys. That order id is real, on the
> merchant's Razorpay test account."

**3. Let it hit the cap.** The script then tries the ₹2,499 headphones:

```
  refused  : spend_blocked
    [FAIL] per_transaction_cap     ₹2,499.00 / ₹2,000.00
```

> "And the merchant refuses it exactly as it refuses its own agent — because the
> limits live in the merchant's service layer, not in whichever client is
> calling. Same merchant, different agent, same guardrails."

**Optional, if you have 20 more seconds:** the same server over stdio in Claude
Desktop (config in [mcp.md](./mcp.md)). Stronger with a name a panel recognises,
but the point is already made.

---

## Clip 2 — Revoking authority, live

**Setup** (before recording — note: **no** `--granted`):

```bash
python demo/reset.py
```

Two browser tabs, both loaded before you hit record: **`/dashboard`** and
**`/chat`**.

**Beat 1 — the agent has no authority** (~15s). In `/chat`:

```
buy a usb-c cable
```

It is refused. Point at the failed bound:

```
Agent authority        ₹349.00 / ₹0.00     ← red
```

> "The agent can't buy anything. Not because of a spend cap — it has no
> authority at all. Nobody has given it any."

**Beat 2 — grant it** (~15s). On `/dashboard`, in **Agent access**: pick
**₹5,000**, **24 hours**, click **Grant agent access**.

> "I'm authorising ₹5,000 for 24 hours. Not per purchase — once. It can now
> spend freely inside that without asking me again."

**Beat 3 — it buys** (~15s). Back in `/chat`:

```
buy a usb-c cable
```

Succeeds. Show `Agent authority ₹349.00 / ₹5,000.00` in green, and the
dashboard's **Spent ₹349.00 of ₹5,000.00**.

**Beat 4 — revoke, and prove it bit** (~25s). This is the clip. On
`/dashboard`, click the red **Revoke access**. The panel flips to the amber
*"No purchasing authority"* state, with the grant form back.

Immediately, in `/chat`:

```
buy another usb-c cable
```

> "Revoked. No confirmation dialog, no cooling-off — and the very next order
> fails. Nothing was cached, so there is no window where a revoked agent can
> still spend."

Point at the bound: `Agent authority ₹349.00 / ₹0.00`.

**Beat 5 — the record** (~10s). Dashboard → **Audit trail**:

```
grant_access   allow -> succeeded  ₹5,000.00  by=buyer
create_order   allow -> succeeded    ₹349.00
revoke_access  allow -> succeeded  ₹4,651.00  by=buyer
create_order   block -> blocked      ₹349.00
```

> "Granting and revoking are audited with the same rigour as the purchase
> itself, in the same table. ₹4,651 of unspent authority withdrawn. A trail that
> showed the money moving but not who authorised it, or when that authority
> ended, would explain half of what happened."

---

## If you have time for one more

Revoke **while an order is waiting for approval**, then try to approve it:

1. Grant ₹5,000. In chat: `buy a wireless mouse` (₹1,299 — above the ₹500
   auto-approve limit, so it is held).
2. On the dashboard, **revoke**.
3. Back in chat, click **Approve ₹1,299.00**.

It fails. The order was already in flight and it still cannot complete — which
is the harder half of "instant", and the one most implementations get wrong.

---

## Recording notes

- **Reset between takes.** `demo/reset.py` exists because the audit trail
  accumulates across attempts and stops being legible.
- **Terminal, not IDE**, for clip 1 — a plain shell reads better at video
  compression than a syntax-highlighted editor pane.
- **Don't narrate over loading.** Both clips are scripted so every pause has
  something on screen worth looking at.
- `demo/mcp_buyer.py` paces itself deliberately. Use `--fast` only for scripted
  checks, never for the recording.
- Numbers in this document match the defaults in `.env.example`. If you have
  changed the caps, the on-screen figures will differ — re-read your own
  `/catalog` policy block before scripting narration.
