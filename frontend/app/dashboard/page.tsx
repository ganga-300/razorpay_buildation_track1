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
    <main className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Merchant dashboard
          </h1>
          <p className="mt-1 text-sm text-muted">
            Every money action the agent took — and every one it was stopped
            from taking.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
          {loading ? <Spinner /> : null}
          Refresh
        </Button>
      </div>

      {error ? (
        <Card className="mb-4 border-danger/40 bg-danger/5 p-4 text-sm text-danger">
          {error}
        </Card>
      ) : null}

      {/* Authority first: whether the agent may act at all comes before how
          much it may spend. */}
      <div className="mb-4">
        <AgentAccess grant={grant} onChanged={load} />
      </div>

      {audit ? (
        <div className="mb-4">
          <SpendMeter budget={audit.budget} />
        </div>
      ) : null}

      {orders ? <SummaryStats summary={orders.summary} /> : null}

      <div className="mt-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <nav className="flex gap-1" aria-label="Dashboard views">
            {(["orders", "audit"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                aria-current={tab === t ? "page" : undefined}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm transition-colors",
                  tab === t
                    ? "bg-elevated text-ink"
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
                className="ml-auto rounded-md border border-border bg-elevated px-2 py-1.5 text-xs"
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
    <div className="px-4 py-10 text-center text-sm text-muted">
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
    <div className="px-4 py-10 text-center text-sm text-muted">
      Could not load this data. Check the backend, then hit Refresh.
    </div>
  );
}
