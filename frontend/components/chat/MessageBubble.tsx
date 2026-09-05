import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

/**
 * The buyer speaks in a pill; the agent speaks on the page.
 *
 * Giving both sides a bubble makes a transcript look like a messaging app.
 * Letting the agent's prose sit directly on paper at a comfortable reading size
 * treats it as the document it is — and the asymmetry alone says who spoke,
 * without a label.
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
    <div className="max-w-prose break-words text-[0.9375rem] leading-[1.6] text-ink">
      {typeof children === "string" ? <AgentProse text={children} /> : children}
    </div>
  );
}

/**
 * Renders the agent's text as prose rather than as preformatted output.
 *
 * `whitespace-pre-wrap` turns a blank line between paragraphs into a full empty
 * line *on top of* the line-height, which at this reading size opened gaps wide
 * enough to look like the layout had broken. Paragraphs are spaced with margin
 * instead, and a run of list lines is set as an actual list so the bullets align
 * and wrap under themselves.
 */
function AgentProse({ text }: { text: string }) {
  const blocks = text.trim().split(/\n{2,}/);

  return (
    <>
      {blocks.map((block, i) => {
        const lines = block.split("\n");
        const isList = lines.every((l) => /^\s*[·•-]\s+/.test(l));

        if (isList) {
          return (
            <ul key={i} className={cn("space-y-1", i > 0 && "mt-3")}>
              {lines.map((line, j) => (
                <li key={j} className="flex gap-2.5">
                  <span aria-hidden className="select-none text-faint">
                    ·
                  </span>
                  <span>{line.replace(/^\s*[·•-]\s+/, "")}</span>
                </li>
              ))}
            </ul>
          );
        }

        return (
          <p key={i} className={cn("whitespace-pre-line", i > 0 && "mt-3")}>
            {block}
          </p>
        );
      })}
    </>
  );
}
