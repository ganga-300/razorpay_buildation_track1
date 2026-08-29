# AutoBuy — Frontend

Next.js 14 (App Router) + TypeScript (strict) + Tailwind CSS.

## Run

```bash
npm install
cp .env.example .env.local
npm run dev
```

Open <http://localhost:3000>. The backend must be running on the URL in
`NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`).

## Layout

```
app/
├── page.tsx        Landing
├── chat/           Conversational checkout
├── dashboard/      Merchant order view
└── globals.css     Theme tokens (light + dark)
components/
├── Nav.tsx
├── ui/             Button · Card · Badge · Table · Spinner
├── BoundChecks.tsx Bounds evaluated, shared by chat and audit trail
├── chat/           ChatWindow · MessageBubble · ProductCard · OrderCard
│                   ToolTrace · ApprovalPrompt · GuardrailNotice
│                   Composer · useChat
└── dashboard/      OrdersTable · AuditTable · SpendMeter · SummaryStats
lib/
├── api.ts          Typed fetch client — the only place fetch is called
├── sse.ts          SSE parser for POST /chat (+ sse.test.ts)
├── razorpay.ts     Checkout script loader and handoff
├── orderStatus.ts  Status → label/tone, shared by chat and dashboard
├── types.ts        Types mirroring backend Pydantic schemas
└── cn.ts           Tailwind-aware class merger
```

## Why a hand-written SSE client

`POST /chat` streams Server-Sent Events, and the browser's native `EventSource`
only issues **GET** requests with no body. `lib/sse.ts` reads the `fetch`
response stream and parses the wire format directly.

Frame boundaries are matched with `/\r?\n\r?\n/`, not `"\n\n"`. The SSE spec
allows LF, CRLF, or CR, and `sse-starlette` emits **CRLF** — splitting on `\n\n`
buffers the whole stream and then fails to parse the concatenated result, so
nothing ever renders. `lib/sse.test.ts` covers that case; it fails against the
naive parser.

## Explainability

`ToolTrace` renders every tool call inline — name, arguments, outcome — with
money-moving calls badged **moves money**. A purchasing agent whose actions are
invisible isn't one anyone should trust with a card.

Payment verification posts to `/payments/verify` rather than going back through
the agent. A signature check is a security control, and a control that only runs
if a language model chooses to call a tool is not a control.

## Tests

```bash
npm run test        # vitest
npm run typecheck   # tsc --noEmit
npm run lint
```

## Design rules

1. **All network access goes through `lib/api.ts`.** No component calls `fetch`.
2. **Colors come from semantic tokens** (`bg-surface`, `text-muted`, `text-brand`)
   defined once in `globals.css` — never raw hex in a component.
3. **Components are built once and reused** across `/chat` and `/dashboard`.
4. **`strict` plus `noUncheckedIndexedAccess`** are on. Keep them on.

## Scripts

| Command | Does |
|---|---|
| `npm run dev` | Dev server |
| `npm run build` | Production build |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | ESLint |
| `npm run test` | Vitest |


## The approval gate

`ApprovalPrompt` calls `POST /orders/{id}/approve`. Approval is tied to a
specific order id and is never inferred from the buyer typing "yes" — a
confirmation the model reads out of chat text is one a prompt injection can
forge; a button press is an action only the person at the keyboard can take.

`GuardrailNotice` and `BoundChecks` render the bounds that were evaluated, with
the observed value against each limit. That is what turns "blocked" into an
explanation.
