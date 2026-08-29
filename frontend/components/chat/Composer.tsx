"use client";

import { useState, type FormEvent, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";

export function Composer({
  onSend,
  disabled,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
}) {
  const [value, setValue] = useState("");

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
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
    <form
      onSubmit={submit}
      className="flex items-end gap-2 border-t border-border bg-elevated p-3"
    >
      <label htmlFor="composer" className="sr-only">
        Message the purchasing agent
      </label>
      <textarea
        id="composer"
        rows={1}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask for something to buy…"
        className="max-h-32 min-h-[2.5rem] flex-1 resize-y rounded-lg border border-border
                   bg-surface px-3 py-2 text-sm outline-none
                   focus-visible:border-brand disabled:opacity-50"
        disabled={disabled}
      />
      <Button type="submit" disabled={disabled || !value.trim()}>
        {disabled ? <Spinner /> : null}
        Send
      </Button>
    </form>
  );
}
