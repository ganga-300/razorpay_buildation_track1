"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

/**
 * Route-level error boundary.
 *
 * A purchasing app must never show a blank page after a crash — the buyer has
 * no way to tell an interface failure from a payment that half-happened. This
 * says which it was.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Route error:", error);
  }, [error]);

  return (
    <main className="mx-auto max-w-2xl px-4 py-16">
      <Card className="border-danger/40 bg-danger/5 p-6">
        <h1 className="text-lg font-semibold text-danger">
          Something went wrong on this page
        </h1>
        <p className="mt-2 text-sm text-muted">
          This is an interface error. It did not charge anything and it did not
          change any order — every money action is recorded server-side, so the
          dashboard remains the source of truth.
        </p>

        {error.message ? (
          <p className="mt-3 rounded-md border border-border bg-surface px-3 py-2 font-mono text-xs">
            {error.message}
          </p>
        ) : null}
        {error.digest ? (
          <p className="mt-2 font-mono text-[11px] text-muted">
            digest: {error.digest}
          </p>
        ) : null}

        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={reset}>Try again</Button>
          <Button variant="secondary" onClick={() => location.assign("/dashboard")}>
            Open the dashboard
          </Button>
        </div>
      </Card>
    </main>
  );
}
