import Link from "next/link";

import { GuardrailPreview } from "@/components/landing/GuardrailPreview";
import { Reveal } from "@/components/motion/Reveal";
import { buttonClasses } from "@/components/ui/Button";

const SURFACES = [
  {
    href: "/chat",
    label: "Conversational checkout",
    body: "Talk to the purchasing agent. It searches the catalog, proposes an order, and asks for approval when the amount crosses the gate.",
  },
  {
    href: "/dashboard",
    label: "Merchant audit trail",
    body: "Every gated decision the agent made — the bound checked, the verdict, the reason, and the order it produced.",
  },
] as const;

const BANDS = [
  {
    limit: "≤ ₹500",
    verdict: "Executes",
    body: "Within the auto-approve limit. The agent buys without asking.",
  },
  {
    limit: "₹500 – ₹2,000",
    verdict: "Held for you",
    body: "Above the limit, within the caps. Nothing is charged until you approve it.",
  },
  {
    limit: "> ₹2,000",
    verdict: "Refused",
    body: "Over the per-transaction cap. Razorpay is never contacted, and the refusal is recorded.",
  },
] as const;

export default function HomePage() {
  return (
    <main>
      {/* ---- hero ---------------------------------------------------- */}
      <section className="mx-auto max-w-6xl px-5 pb-24 pt-16 sm:px-8 sm:pb-32 sm:pt-24">
        <Reveal>
          <p className="text-eyebrow uppercase text-faint">
            Razorpay AI Buildathon · Track 01
          </p>
        </Reveal>

        <Reveal delay={80}>
          {/*
            Mixed weight across two lines: the qualifier recedes, the claim
            lands. One sentence, two visual registers.
          */}
          <h1 className="mt-7 max-w-[16ch] text-hero text-balance">
            <span className="block font-normal text-muted">An agent that</span>
            <span className="block">spends your money.</span>
          </h1>
        </Reveal>

        <div className="mt-10 grid gap-12 lg:grid-cols-[1fr_minmax(0,26rem)] lg:items-end lg:gap-16">
          <Reveal delay={160}>
            <p className="max-w-prose text-lede text-pretty text-muted">
              AutoBuy makes a merchant transactable by an AI buyer end to end —
              with hard spend caps, human approval above a threshold, revocable
              purchasing authority, and an inspectable audit trail behind every
              money action.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link href="/chat" className={buttonClasses("primary", "lg")}>
                Talk to the agent
              </Link>
              <Link href="/dashboard" className={buttonClasses("secondary", "lg")}>
                See the audit trail
              </Link>
            </div>
          </Reveal>

          <Reveal delay={240}>
            <GuardrailPreview />
          </Reveal>
        </div>
      </section>

      {/* ---- the three bands ----------------------------------------- */}
      <section className="border-t border-border bg-elevated/60">
        <div className="mx-auto max-w-6xl px-5 py-20 sm:px-8 sm:py-28">
          <Reveal>
            <p className="text-eyebrow uppercase text-faint">Bounded</p>
            <h2 className="mt-5 max-w-[20ch] text-display text-balance">
              What it may spend, and what it may never spend.
            </h2>
          </Reveal>

          <div className="mt-14 grid gap-px overflow-hidden rounded-2xl border border-border bg-border sm:grid-cols-3">
            {BANDS.map((band, i) => (
              <Reveal key={band.limit} delay={i * 90}>
                <div className="h-full bg-elevated p-6 sm:p-7">
                  <p className="tabular text-[0.8125rem] font-medium text-faint">
                    {band.limit}
                  </p>
                  <p className="mt-4 text-title">{band.verdict}</p>
                  <p className="mt-3 text-[0.8125rem] leading-relaxed text-muted">
                    {band.body}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>

          <Reveal delay={280}>
            <p className="mt-8 max-w-prose text-[0.8125rem] leading-relaxed text-faint">
              Hard caps are checked before the approval threshold — a cap a human
              can click through is not a cap. Every limit is enforced server-side,
              so it holds whether the buyer is our own agent or someone else&rsquo;s.
            </p>
          </Reveal>
        </div>
      </section>

      {/* ---- surfaces ------------------------------------------------- */}
      <section className="mx-auto max-w-6xl px-5 py-20 sm:px-8 sm:py-28">
        <div className="grid gap-4 sm:grid-cols-2">
          {SURFACES.map((surface, i) => (
            <Reveal key={surface.href} delay={i * 90}>
              <Link
                href={surface.href}
                className="group block h-full rounded-2xl border border-border bg-elevated p-7 shadow-card transition-all duration-slow ease hover:-translate-y-1 hover:shadow-lift sm:p-8"
              >
                <div className="flex items-baseline justify-between gap-4">
                  <h3 className="text-title">{surface.label}</h3>
                  <span
                    aria-hidden
                    className="text-lg text-faint transition-transform duration-slow ease group-hover:translate-x-1 group-hover:text-ink"
                  >
                    →
                  </span>
                </div>
                <p className="mt-4 max-w-prose text-[0.875rem] leading-relaxed text-muted">
                  {surface.body}
                </p>
              </Link>
            </Reveal>
          ))}
        </div>
      </section>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-10 text-[0.75rem] text-faint sm:px-8">
          <p>Razorpay test mode. No real money moves.</p>
          <p className="font-mono">autobuy</p>
        </div>
      </footer>
    </main>
  );
}
