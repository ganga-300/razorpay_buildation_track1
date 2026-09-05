"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
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
      <Card className="border-warn/30 bg-warn/[0.04] p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-eyebrow uppercase text-warn">Agent access</p>
            <h2 className="mt-3 text-title">No purchasing authority</h2>
            <p className="mt-2 max-w-prose text-[0.8125rem] leading-relaxed text-muted">
              The agent cannot buy anything. Grant a capped, expiring allowance
              and it can then buy freely within it without asking again — and you
              can withdraw it at any time.
            </p>
          </div>
          <Badge tone="warn">not granted</Badge>
        </div>

        <div>
          <div className="mt-6 flex flex-wrap items-end gap-4">
            <div>
              <span className="mb-2 block text-eyebrow uppercase text-faint">
                Spending cap
              </span>
              <div className="flex gap-1">
                {PRESETS.map((p) => (
                  <button
                    key={p.minor}
                    type="button"
                    onClick={() => setCap(p.minor)}
                    className={cn(
                      "tabular rounded-full border px-3.5 py-1.5 text-[0.75rem]",
                      "transition-all duration-fast ease active:scale-95",
                      cap === p.minor
                        ? "border-transparent bg-brand text-on-brand"
                        : "border-border bg-elevated text-muted hover:border-ink/25 hover:text-ink",
                    )}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label
                htmlFor="grant-hours"
                className="mb-2 block text-eyebrow uppercase text-faint"
              >
                Expires in
              </label>
              <select
                id="grant-hours"
                value={hours}
                onChange={(e) => setHours(Number(e.target.value))}
                className="h-8 rounded-full border border-border bg-elevated px-3.5 text-[0.75rem] transition-colors duration-fast hover:border-ink/25"
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

          {error ? (
            <p className="mt-3 text-[0.75rem] text-danger">{error}</p>
          ) : null}
        </div>
      </Card>
    );
  }

  // ---- live authority ----------------------------------------------------

  const pct = Math.round(grant.used_fraction * 100);

  return (
    <Card className="p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="flex items-center gap-2 text-eyebrow uppercase text-faint">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-ok" />
            Agent access · active
          </p>
          <p className="tabular mt-3 text-[1.75rem] font-semibold leading-none tracking-[-0.04em]">
            {grant.remaining.display}
          </p>
          <p className="mt-2 text-[0.8125rem] text-muted">
            still authorised of {grant.spend_cap.display} ·{" "}
            {expiryLabel(grant.expires_at)}
          </p>
        </div>

        <Button size="sm" variant="danger" onClick={handleRevoke} disabled={busy}>
          {busy ? <Spinner /> : null}
          Revoke access
        </Button>
      </div>

      <div className="mt-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2 text-[0.75rem] text-faint">
          <span>
            Spent <span className="tabular text-ink">{grant.spent.display}</span>
          </span>
          <span className="tabular">{pct}% used</span>
        </div>

        <div
          className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-sunken"
          role="meter"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Grant used: ${pct}%`}
        >
          <div
            className={cn(
              "h-full rounded-full transition-[width] duration-slow ease",
              pct >= 90 ? "bg-danger" : pct >= 70 ? "bg-warn" : "bg-ok",
            )}
            style={{
              width: `${Math.max(pct, grant.spent.amount_minor > 0 ? 1.5 : 0)}%`,
            }}
          />
        </div>

        <p className="mt-4 border-t border-border pt-4 text-[0.75rem] leading-relaxed text-faint">
          Revoking takes effect on the very next order — including one already
          waiting for your approval.
        </p>

        {error ? (
          <p className="mt-3 text-[0.75rem] text-danger">{error}</p>
        ) : null}
      </div>
    </Card>
  );
}
