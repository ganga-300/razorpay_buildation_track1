import Link from "next/link";

const SURFACES = [
  {
    href: "/chat",
    title: "Conversational checkout",
    body: "Talk to the purchasing agent. It searches the catalog, proposes an order, and asks for approval when the amount crosses the gate.",
  },
  {
    href: "/dashboard",
    title: "Merchant audit trail",
    body: "Every gated decision the agent made — the bound checked, the verdict, the reason, and the order it produced.",
  },
] as const;

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-10 px-6 py-16">
      <header className="space-y-4">
        <span className="inline-block rounded-full border border-border px-3 py-1 text-xs font-medium uppercase tracking-wider text-muted">
          Razorpay test mode
        </span>
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
          AutoBuy
        </h1>
        <p className="max-w-prose text-lg text-muted">
          An AI purchasing agent that makes a merchant transactable end to end —
          with hard spend caps, human approval above a threshold, and an
          inspectable audit trail behind every money action.
        </p>
      </header>

      <nav className="grid gap-4 sm:grid-cols-2">
        {SURFACES.map((s) => (
          <Link
            key={s.href}
            href={s.href}
            className="group rounded-xl border border-border bg-elevated p-5 transition-colors hover:border-brand"
          >
            <h2 className="font-medium group-hover:text-brand">{s.title}</h2>
            <p className="mt-2 text-sm text-muted">{s.body}</p>
          </Link>
        ))}
      </nav>

      <footer className="text-sm text-muted">
        Milestone 0 — scaffold. Catalog, agent, and guardrails land next.
      </footer>
    </main>
  );
}
