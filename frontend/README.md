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
├── chat/           Conversational checkout (M3)
├── dashboard/      Merchant audit trail (M3)
└── globals.css     Theme tokens (light + dark)
components/
├── ui/             Button · Card · Badge · Table
├── chat/           ChatWindow · MessageBubble · ApprovalPrompt
└── dashboard/      AuditTable · SpendMeter · OrderCard
lib/
├── api.ts          Typed fetch client — the only place fetch is called
├── types.ts        Types mirroring backend Pydantic schemas
└── cn.ts           Tailwind-aware class merger
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
