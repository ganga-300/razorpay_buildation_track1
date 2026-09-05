import { Spinner } from "@/components/ui/Spinner";
import { cn } from "@/lib/cn";
import type { ErrorPayload } from "@/lib/types";

export type ToolStatus = "running" | "ok" | "error";

/**
 * One tool invocation, as a log line.
 *
 * This is the explainability surface: the buyer sees which tool the agent
 * reached for, with what arguments, and whether it succeeded. It is set in mono
 * at a small size and low contrast on purpose — present and inspectable, but
 * never competing with what the agent actually said. Money-moving calls are the
 * exception and carry a visible mark.
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
        "rounded-xl border px-3.5 py-2.5 font-mono text-[0.6875rem] leading-relaxed",
        "transition-colors duration-slow ease",
        status === "error"
          ? "border-danger/25 bg-danger/[0.04]"
          : "border-border bg-sunken/50",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        {status === "running" ? (
          <Spinner className="h-2.5 w-2.5 border text-faint" />
        ) : (
          <span
            aria-hidden
            className={cn(
              "inline-block h-1.5 w-1.5 rounded-full transition-colors duration-slow",
              status === "ok" ? "bg-ok" : "bg-danger",
            )}
          />
        )}

        <span className="font-medium text-ink">{tool}</span>

        {mutatesMoney ? (
          <span className="rounded-full bg-warn/10 px-1.5 py-0.5 text-[0.625rem] font-medium text-warn">
            moves money
          </span>
        ) : null}

        {status === "running" ? (
          <span className="text-faint">running…</span>
        ) : null}
      </div>

      {entries.length > 0 ? (
        <dl className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
          {entries.map(([key, value]) => (
            <div key={key} className="flex gap-1">
              <dt className="text-faint">{key}:</dt>
              <dd className="text-muted">{String(value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {error ? (
        <p className="mt-2 font-sans text-[0.75rem] leading-relaxed text-danger">
          <span className="font-mono font-medium">{error.code}</span> — {error.message}
        </p>
      ) : null}
    </div>
  );
}
