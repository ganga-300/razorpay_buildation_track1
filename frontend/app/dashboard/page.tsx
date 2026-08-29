"use client";

import { useCallback, useEffect, useState } from "react";

import { OrdersTable } from "@/components/dashboard/OrdersTable";
import { SummaryStats } from "@/components/dashboard/SummaryStats";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { getOrders } from "@/lib/api";
import type { OrderListResponse } from "@/lib/types";

export default function DashboardPage() {
  const [data, setData] = useState<OrderListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getOrders());
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load orders.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Merchant dashboard
          </h1>
          <p className="mt-1 text-sm text-muted">
            Every order the agent created, including the ones that failed.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
          {loading ? <Spinner /> : null}
          Refresh
        </Button>
      </div>

      {error ? (
        <Card className="border-danger/40 bg-danger/5 p-4 text-sm text-danger">
          {error}
        </Card>
      ) : null}

      {data ? (
        <div className="space-y-4">
          <SummaryStats summary={data.summary} />
          <Card className="overflow-hidden">
            <CardHeader
              title="Orders"
              subtitle={`${data.count} record${data.count === 1 ? "" : "s"}, newest first`}
            />
            <OrdersTable orders={data.orders} />
          </Card>
        </div>
      ) : loading ? (
        <Card className="p-10 text-center text-sm text-muted">
          <Spinner /> Loading orders…
        </Card>
      ) : null}
    </main>
  );
}
