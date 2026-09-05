"use client";

import { useState, type FormEvent, type KeyboardEvent } from "react";

import { Spinner } from "@/components/ui/Spinner";
import { cn } from "@/lib/cn";

/**
 * One rounded field with the send control inside it.
 *
 * A separate button beside the input reads like a form; a single capsule reads
 * like somewhere to talk. The whole thing takes the focus ring, so the target
 * you see is the target you get.
 */
export function Composer({
  onSend,
  disabled,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
}) {
  const [value, setValue] = useState("");
  const canSend = Boolean(value.trim()) && !disabled;

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!canSend) return;
    onSend(value.trim());
    setValue("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter inserts a newline.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form onSubmit={submit} className="relative">
      <label htmlFor="composer" className="sr-only">
        Message the purchasing agent
      </label>

      <div
        className={cn(
          "flex items-end gap-2 rounded-2xl border border-border bg-elevated",
          "py-2 pl-4 pr-2 shadow-card transition-all duration-fast ease",
          "focus-within:border-ink/25 focus-within:shadow-lift",
        )}
      >
        <textarea
          id="composer"
          rows={1}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask for something to buy…"
          disabled={disabled}
          className={cn(
            "max-h-40 min-h-[2.25rem] flex-1 resize-none bg-transparent py-1.5",
            "text-[0.9375rem] leading-relaxed outline-none",
            "placeholder:text-faint disabled:opacity-50",
          )}
        />

        <button
          type="submit"
          disabled={!canSend}
          aria-label="Send message"
          className={cn(
            "mb-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full",
            "transition-all duration-fast ease active:scale-95",
            canSend
              ? "bg-brand text-on-brand hover:opacity-90"
              : "bg-sunken text-faint",
          )}
        >
          {disabled ? <Spinner /> : <span aria-hidden className="text-sm">↑</span>}
        </button>
      </div>
    </form>
  );
}
