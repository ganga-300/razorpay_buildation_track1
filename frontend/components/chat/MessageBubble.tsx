import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

/**
 * The buyer speaks in a pill; the agent speaks on the page.
 *
 * Giving both sides a bubble makes a transcript look like a chat toy. Letting
 * the agent's prose sit directly on paper at a comfortable reading size treats
 * it as the document it is — and the asymmetry alone is enough to tell you who
 * said what, without a label.
 */
export function MessageBubble({
  role,
  children,
}: {
  role: "user" | "agent";
  children: ReactNode;
}) {
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div
          className={cn(
            "max-w-[85%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5",
            "text-[0.875rem] leading-relaxed text-on-brand",
            "whitespace-pre-wrap break-words",
          )}
        >
          {children}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-prose whitespace-pre-wrap break-words text-[0.9375rem] leading-[1.65] text-ink">
      {children}
    </div>
  );
}
