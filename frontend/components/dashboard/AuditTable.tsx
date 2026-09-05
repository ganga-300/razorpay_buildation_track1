"use client";

import { useState } from "react";

import { BoundChecks } from "@/components/BoundChecks";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Table, type Column } from "@/components/ui/Table";
import type { AuditDecision, AuditEntry, AuditOutcome } from "@/lib/types";

const DECISION: Record<AuditDecision, { label: string; tone: BadgeTone }> = {
  allow: { label: "Allowed", tone: "ok" },
  require_approval: { label: "Approval required", tone: "warn" },
  block: { label: "Blocked", tone: "danger" },
};

const OUTCOME: Record<AuditOutcome, { label: string; tone: BadgeTone }> = {
  pending: { label: "Pending", tone: "neutral" },
  awaiting_approval: { label: "Awaiting human", tone: "warn" },
  succeeded: { label: "Succeeded", tone: "ok" },
  failed: { label: "Failed", tone: "danger" },
  blocked: { label: "Blocked", tone: "danger" },
  declined: { label: "Declined", tone: "neutral" },
  expired: { label: "Expired", tone: "neutral" },
};

function when(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
}

/**
 * The audit trail.
 *
 * Each row expands to show the exact bounds that were evaluated at the time.
 * That snapshot is what makes a past decision explainable after the configured
 * caps have moved on.
 */
export function AuditTable({ entries }: { entries: AuditEntry[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  const columns: Column<AuditEntry>[] = [
    {
      key: "when",
      header: "When",
      render: (e) => (
        <div className="min-w-0">
          <span className="whitespace-nowrap text-[0.75rem]">{when(e.created_at)}</span>
          <code className="mt-1 block font-mono text-[0.6875rem] text-faint">
            {e.id}
          </code>
        </div>
      ),
    },
    {
      key: "action",
      header: "Action",
      render: (e) => (
        <div className="min-w-0 max-w-[14rem]">
          <code className="font-mono text-[0.75rem]">{e.action}</code>
          <span className="mt-1 block truncate text-[0.6875rem] text-faint">
            {e.product?.name ?? "—"}
            {e.quantity ? ` × ${e.quantity}` : ""}
          </span>
        </div>
      ),
    },
    {
      key: "amount",
      header: "Amount",
      numeric: true,
      render: (e) => (
        <span className="font-semibold tracking-[-0.02em]">{e.amount.display}</span>
      ),
    },
    {
      key: "verdict",
      // Decision and outcome read as one story — what the gate decided, then
      // what actually happened — so they share a cell rather than sitting in
      // two columns that push the reason off screen.
      header: "Decision → outcome",
      render: (e) => (
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-1">
            <Badge tone={DECISION[e.decision].tone}>
              {DECISION[e.decision].label}
            </Badge>
            <span aria-hidden className="text-muted">
              →
            </span>
            <Badge tone={OUTCOME[e.outcome].tone}>
              {OUTCOME[e.outcome].label}
            </Badge>
          </div>
          <p className="tabular text-[0.6875rem] text-faint">
            {e.approved_by ? `by ${e.approved_by} · ` : ""}
            {e.attempts} {e.attempts === 1 ? "try" : "tries"}
            {e.duration_ms !== null ? ` · ${e.duration_ms}ms` : ""}
          </p>
          {e.failure?.code ? (
            <code className="font-mono text-[0.6875rem] text-danger">
              {e.failure.code}
            </code>
          ) : null}
        </div>
      ),
    },
    {
      key: "why",
      header: "Why",
      render: (e) => (
        <div className="max-w-[24rem]">
          <button
            type="button"
            onClick={() => setExpanded(expanded === e.id ? null : e.id)}
            className="text-left text-[0.75rem] leading-relaxed text-muted underline-offset-4 transition-colors duration-fast hover:text-ink hover:underline"
            aria-expanded={expanded === e.id}
          >
            <span className={expanded === e.id ? "" : "line-clamp-2"}>
              {e.reason}
            </span>
          </button>
          {expanded === e.id ? (
            <div className="mt-3 animate-scale-in rounded-xl border border-border bg-sunken/60 p-3">
              <p className="mb-2 text-eyebrow uppercase text-faint">
                Bounds checked at decision time
              </p>
              <BoundChecks checks={e.checks} />
              {e.failure?.reason ? (
                <p className="mt-2 text-[0.6875rem] leading-relaxed text-danger">
                  {e.failure.reason}
                </p>
              ) : null}
              {e.order_id ? (
                <code className="mt-2 block font-mono text-[0.6875rem] text-faint">
                  {e.order_id}
                </code>
              ) : null}
            </div>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <Table
      columns={columns}
      rows={entries}
      rowKey={(e) => e.id}
      empty="No money decisions recorded yet."
    />
  );
}
