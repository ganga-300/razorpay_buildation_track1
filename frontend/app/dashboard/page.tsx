"use client";

import { useCallback, useEffect, useState } from "react";

import { AgentAccess } from "@/components/dashboard/AgentAccess";
import { AuditTable } from "@/components/dashboard/AuditTable";
import { OrdersTable } from "@/components/dashboard/OrdersTable";
import { SpendMeter } from "@/components/dashboard/SpendMeter";
import { SummaryStats } from "@/components/dashboard/SummaryStats";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { Reveal } from "@/components/motion/Reveal";
import { getAudit, getGrants, getOrders } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { AuditListResponse, Grant, OrderListResponse } from "@/lib/types";

type Tab = "orders" | "audit";

const DECISION_FILTERS = [
  { value: "", label: "All decisions" },
  { value: "allow", label: "Allowed" },
  { value: "require_approval", label: "Approval required" },
  { value: "block", label: "Blocked" },
] as const;

export default function DashboardPage() {
  const [tab, setTab] = useState<Tab>("orders");
  const [decision, setDecision] = useState("");
  const [orders, setOrders] = useState<OrderListResponse | null>(null);
  const [audit, setAudit] = useState<AuditListResponse | null>(null);
  const [grant, setGrant] = useState<Grant | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [o, a, g] = await Promise.all([
        getOrders(),
        getAudit(decision ? { decision } : {}),
        getGrants(),
      ]);
      setOrders(o);
      setAudit(a);
      setGrant(g.active);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load data.");
    } finally {
      setLoading(false);
    }
  }, [decision]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className="mx-auto max-w-6xl px-5 pb-24 pt-10 sm:px-8 sm:pt-14">
      <div className="mb-10 flex flex-wrap items-end justify-between gap-6">
        <div>
          <p className="text-eyebrow uppercase text-faint">Merchant</p>
          <h1 className="mt-4 max-w-[20ch] text-display text-balance">
            Every money action the agent took.
          </h1>
          <p className="mt-4 max-w-prose text-lede text-muted">
            And every one it was stopped from taking.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
          {loading ? <Spinner /> : null}
          Refresh
        </Button>
      </div>

      {error ? (
        <div className="mb-6 rounded-xl bg-danger/[0.06] px-4 py-3 text-[0.8125rem] text-danger">
          {error}
        </div>
      ) : null}

      {/* Authority first: whether the agent may act at all comes before how
          much it may spend. */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Reveal>
          <AgentAccess grant={grant} onChanged={load} />
        </Reveal>
        {audit ? (
          <Reveal delay={80}>
            <SpendMeter budget={audit.budget} />
          </Reveal>
        ) : null}
      </div>

      {orders ? (
        <Reveal delay={140} className="mt-4 block">
          <SummaryStats summary={orders.summary} />
        </Reveal>
      ) : null}

      <div className="mt-10">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <nav
            className="flex gap-1 rounded-full border border-border bg-elevated p-1"
            aria-label="Dashboard views"
          >
            {(["orders", "audit"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                aria-current={tab === t ? "page" : undefined}
                className={cn(
                  "rounded-full px-4 py-1.5 text-[0.8125rem] transition-all duration-fast ease",
                  tab === t
                    ? "bg-brand text-on-brand"
                    : "text-muted hover:text-ink",
                )}
              >
                {t === "orders" ? "Orders" : "Audit trail"}
              </button>
            ))}
          </nav>

          {tab === "audit" ? (
            <>
              <label htmlFor="decision-filter" className="sr-only">
                Filter by decision
              </label>
              <select
                id="decision-filter"
                value={decision}
                onChange={(e) => setDecision(e.target.value)}
                className="ml-auto h-8 rounded-full border border-border bg-elevated px-3.5 text-[0.75rem] transition-colors duration-fast hover:border-ink/25"
              >
                {DECISION_FILTERS.map((f) => (
                  <option key={f.value} value={f.value}>
                    {f.label}
                  </option>
                ))}
              </select>
              {audit ? (
                <Badge tone="danger">
                  {audit.summary.blocked_amount.display} blocked
                </Badge>
              ) : null}
            </>
          ) : null}
        </div>

        <Card className="overflow-hidden">
          {tab === "orders" ? (
            <>
              <CardHeader
                title="Orders"
                subtitle={
                  orders
                    ? `${orders.count} record${orders.count === 1 ? "" : "s"}, newest first`
                    : undefined
                }
              />
              {orders ? (
                <OrdersTable orders={orders.orders} />
              ) : loading ? (
                <Loading />
              ) : (
                <Unavailable />
              )}
            </>
          ) : (
            <>
              <CardHeader
                title="Audit trail"
                subtitle="Every gated decision, written before the action ran. Click a reason to see the bounds checked."
              />
              {audit ? (
                <AuditTable entries={audit.entries} />
              ) : loading ? (
                <Loading />
              ) : (
                <Unavailable />
              )}
            </>
          )}
        </Card>
      </div>
    </main>
  );
}

function Loading() {
  return (
    <div className="px-5 py-16 text-center text-[0.8125rem] text-muted">
      <Spinner /> Loading…
    </div>
  );
}

/**
 * Shown when a load failed. A panel that keeps saying "Loading…" after the
 * request already failed is worse than an error — on a page about money, it
 * implies data is on its way when none is coming.
 */
function Unavailable() {
  return (
    <div className="px-5 py-16 text-center text-[0.8125rem] text-muted">
      Could not load this data. Check the backend, then hit Refresh.
    </div>
  );
}
