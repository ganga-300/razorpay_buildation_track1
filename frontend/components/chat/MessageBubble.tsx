import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

export function MessageBubble({
  role,
  children,
}: {
  role: "user" | "agent";
  children: ReactNode;
}) {
  const isUser = role === "user";

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] whitespace-pre-wrap break-words rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
          isUser
            ? "rounded-br-sm bg-brand text-white"
            : "rounded-bl-sm border border-border bg-elevated text-ink",
        )}
      >
        {children}
      </div>
    </div>
  );
}
