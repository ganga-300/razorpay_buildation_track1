"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, grantAccess, revokeGrant } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Grant } from "@/lib/types";

const PRESETS = [
  { label: "₹1,000", minor: 100_000 },
  { label: "₹5,000", minor: 500_000 },
  { label: "₹10,000", minor: 1_000_000 },
] as const;

function expiryLabel(iso: string | null): string {
  if (!iso) return "no expiry";
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms)) return "no expiry";
  if (ms <= 0) return "expired";
  const hours = Math.round(ms / 3_600_000);
  return hours >= 24 ? `${Math.round(hours / 24)}d left` : `${hours}h left`;
}

/**
 * The consent lifecycle, made operable.
 *
 * The spend caps bound how much can move at a time. This bounds whether the
 * agent may act at all — and the revoke button is the point: an authority you
 * cannot withdraw instantly is not a grant, it is a transfer. Revoking takes
 * effect on the very next order, with no confirmation step in the way.
 */
export function AgentAccess({
  grant,
  onChanged,
}: {
  grant: Grant | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cap, setCap] = useState(500_000);
  const [hours, setHours] = useState(24);

  function describe(cause: unknown): string {
    if (cause instanceof ApiError) return cause.detail?.message ?? cause.message;
    return cause instanceof Error ? cause.message : "That didn't work.";
  }

  async function handleGrant() {
    setError(null);
    setBusy(true);
    try {
      await grantAccess({ spend_cap_minor: cap, expires_in_hours: hours });
      onChanged();
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setBusy(false);
    }
  }

  async function handleRevoke() {
    if (!grant) return;
    setError(null);
    setBusy(true);
    try {
      await revokeGrant(grant.id, "buyer", "Revoked from the merchant dashboard.");
      onChanged();
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setBusy(false);
    }
  }

  // ---- no live authority -------------------------------------------------

  if (!grant) {
    return (
      <Card className="border-warn/50 bg-warn/5">
        <CardHeader
          title="Agent access"
          subtitle="The agent has no purchasing authority and cannot buy anything."
          action={<Badge tone="warn">not granted</Badge>}
        />
        <div className="px-4 py-3">
          <p className="text-xs text-muted">
            Grant a capped, expiring allowance. The agent can then buy freely
            within it without asking again — and you can withdraw it at any time.
          </p>

          <div className="mt-3 flex flex-wrap items-end gap-3">
            <div>
              <span className="mb-1 block text-xs text-muted">Spending cap</span>
              <div className="flex gap-1">
                {PRESETS.map((p) => (
                  <button
                    key={p.minor}
                    type="button"
                    onClick={() => setCap(p.minor)}
                    className={cn(
                      "rounded-md border px-2.5 py-1 text-xs transition-colors",
                      cap === p.minor
                        ? "border-brand text-brand"
                        : "border-border text-muted hover:text-ink",
                    )}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label htmlFor="grant-hours" className="mb-1 block text-xs text-muted">
                Expires in
              </label>
              <select
                id="grant-hours"
                value={hours}
                onChange={(e) => setHours(Number(e.target.value))}
                className="rounded-md border border-border bg-elevated px-2 py-1.5 text-xs"
              >
                <option value={1}>1 hour</option>
                <option value={24}>24 hours</option>
                <option value={168}>7 days</option>
              </select>
            </div>

            <Button size="sm" onClick={handleGrant} disabled={busy}>
              {busy ? <Spinner /> : null}
              Grant agent access
            </Button>
          </div>

          {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}
        </div>
      </Card>
    );
  }

  // ---- live authority ----------------------------------------------------

  const pct = Math.round(grant.used_fraction * 100);

  return (
    <Card>
      <CardHeader
        title="Agent access"
        subtitle={`Granted ${grant.spend_cap.display} · ${expiryLabel(grant.expires_at)}`}
        action={
          <div className="flex items-center gap-2">
            <Badge tone="ok">active</Badge>
            <Button size="sm" variant="danger" onClick={handleRevoke} disabled={busy}>
              {busy ? <Spinner /> : null}
              Revoke access
            </Button>
          </div>
        }
      />

      <div className="px-4 py-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
          <span className="text-muted">
            Spent{" "}
            <span className="font-semibold tabular-nums text-ink">
              {grant.spent.display}
            </span>{" "}
            of {grant.spend_cap.display}
          </span>
          <span className="text-muted">
            <span className="font-semibold tabular-nums text-ink">
              {grant.remaining.display}
            </span>{" "}
            still authorised
          </span>
        </div>

        <div
          className="mt-2 h-2 w-full overflow-hidden rounded-full bg-surface"
          role="meter"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Grant used: ${pct}%`}
        >
          <div
            className={cn(
              "h-full rounded-full transition-all",
              pct >= 90 ? "bg-danger" : pct >= 70 ? "bg-warn" : "bg-ok",
            )}
            style={{ width: `${Math.max(pct, grant.spent.amount_minor > 0 ? 2 : 0)}%` }}
          />
        </div>

        <p className="mt-2 text-[11px] text-muted">
          Revoking takes effect on the very next order — including one already
          waiting for your approval.
        </p>

        {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}
      </div>
    </Card>
  );
}
