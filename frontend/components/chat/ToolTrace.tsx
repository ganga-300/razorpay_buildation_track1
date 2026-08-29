import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { cn } from "@/lib/cn";
import type { ErrorPayload } from "@/lib/types";

export type ToolStatus = "running" | "ok" | "error";

/**
 * One tool invocation, shown inline in the transcript.
 *
 * This is the explainability surface: the buyer sees exactly which tool the
 * agent reached for, with what arguments, and whether it succeeded — money-
 * moving calls marked as such. A purchase agent whose actions are invisible
 * is not one anybody should trust with a card.
 */
export function ToolTrace({
  tool,
  args,
  status,
  mutatesMoney,
  error,
}: {
  tool: string;
  args: Record<string, unknown>;
  status: ToolStatus;
  mutatesMoney: boolean;
  error?: ErrorPayload | null;
}) {
  const entries = Object.entries(args).filter(
    ([, value]) => value !== null && value !== undefined && value !== "",
  );

  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2 text-xs",
        status === "error"
          ? "border-danger/40 bg-danger/5"
          : "border-border bg-surface",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        {status === "running" ? (
          <Spinner className="text-muted" />
        ) : (
          <span
            aria-hidden
            className={cn(
              "inline-block h-1.5 w-1.5 rounded-full",
              status === "ok" ? "bg-ok" : "bg-danger",
            )}
          />
        )}

        <code className="font-mono font-medium">{tool}</code>

        {mutatesMoney ? <Badge tone="warn">moves money</Badge> : null}

        {status === "running" ? (
          <span className="text-muted">running…</span>
        ) : null}
      </div>

      {entries.length > 0 ? (
        <dl className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-muted">
          {entries.map(([key, value]) => (
            <div key={key} className="flex gap-1">
              <dt className="font-mono">{key}:</dt>
              <dd className="font-mono text-ink">{String(value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {error ? (
        <p className="mt-1.5 text-danger">
          <span className="font-mono font-medium">{error.code}</span>
          {" — "}
          {error.message}
        </p>
      ) : null}
    </div>
  );
}
