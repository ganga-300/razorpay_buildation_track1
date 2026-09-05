"use client";

import { useEffect, useRef } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ApprovalPrompt } from "./ApprovalPrompt";
import { Composer } from "./Composer";
import { GuardrailNotice } from "./GuardrailNotice";
import { MessageBubble } from "./MessageBubble";
import { OrderCard } from "./OrderCard";
import { ProductGrid } from "./ProductCard";
import { ToolTrace } from "./ToolTrace";
import { useChat } from "./useChat";
import type { Order } from "@/lib/types";
import type { ChatItem } from "./types";

const SUGGESTIONS = [
  "I need a cable for my laptop, under ₹500",
  "Show me wireless headphones",
  "I want a bag for commuting",
] as const;

export function ChatWindow() {
  const { items, isStreaming, intent, agentMode, model, send, reset, replaceOrder } =
    useChat();
  const scrollRef = useRef<HTMLDivElement>(null);

  // Scroll the transcript container directly rather than calling
  // scrollIntoView on a sentinel: the sentinel approach targets the nearest
  // scrollable ancestor and, with smooth behaviour, races the layout of cards
  // that are still being added — which left new messages below the fold.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [items]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center gap-3 pb-5">
        <div className="flex items-center gap-2">
          {/* A scripted turn must never be mistaken for the model. */}
          {agentMode === "scripted" ? (
            <Badge tone="warn" title="Deterministic keyword planner — no model call">
              scripted planner
            </Badge>
          ) : model ? (
            <Badge tone="neutral">{model}</Badge>
          ) : null}
          {intent ? <Badge tone="brand">{intent}</Badge> : null}
        </div>

        {items.length > 0 ? (
          <Button variant="ghost" size="sm" onClick={reset} className="ml-auto">
            New chat
          </Button>
        ) : null}
      </header>

      <div
        ref={scrollRef}
        className="min-h-0 flex-1 space-y-5 overflow-y-auto pb-6 [contain:paint]"
      >
        {items.length === 0 ? (
          <EmptyState onPick={send} />
        ) : (
          items.map((item) => (
            // Keyed by a stable id, so each entry mounts — and therefore
            // animates — exactly once.
            <div key={item.id} className="animate-rise">
              <ChatItemView item={item} onSettled={replaceOrder} />
            </div>
          ))
        )}

        {isStreaming ? <ThinkingLine /> : null}
      </div>

      <div className="pt-1">
        <Composer onSend={send} disabled={isStreaming} />
      </div>
    </div>
  );
}

/** A quiet pulse while the agent works, so the wait has a heartbeat. */
function ThinkingLine() {
  return (
    <div className="flex items-center gap-2 text-[0.8125rem] text-faint">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 animate-pulse rounded-full bg-faint"
          style={{ animationDelay: `${i * 160}ms` }}
        />
      ))}
      <span className="ml-1">thinking</span>
    </div>
  );
}

function ChatItemView({
  item,
  onSettled,
}: {
  item: ChatItem;
  onSettled: (order: Order) => void;
}) {
  switch (item.kind) {
    case "user":
      return <MessageBubble role="user">{item.text}</MessageBubble>;

    case "agent":
      return <MessageBubble role="agent">{item.text}</MessageBubble>;

    case "tool":
      return (
        <ToolTrace
          tool={item.tool}
          args={item.args}
          status={item.status}
          mutatesMoney={item.mutatesMoney}
          error={item.error}
        />
      );

    case "products":
      return <ProductGrid products={item.products} />;

    case "order":
      return <OrderCard order={item.order} onSettled={onSettled} />;

    case "guardrail":
      return <GuardrailNotice decision={item.decision} blocked={item.blocked} />;

    case "approval":
      return (
        <ApprovalPrompt
          orderId={item.orderId}
          total={item.total}
          productName={item.productName}
          reason={item.reason}
          checks={item.checks}
          onResolved={onSettled}
        />
      );

    case "error":
      return (
        <div className="rounded-xl bg-danger/[0.06] px-4 py-3 text-[0.8125rem] leading-relaxed text-danger">
          <span className="font-mono font-medium">{item.error.code}</span> —{" "}
          {item.error.message}
        </div>
      );
  }
}

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex h-full flex-col justify-center py-10">
      <h2 className="max-w-[18ch] text-display text-balance">
        What do you need?
      </h2>
      <p className="mt-4 max-w-prose text-[0.9375rem] leading-relaxed text-muted">
        The agent searches the catalog, proposes an order, and stops to ask when
        the amount crosses the approval threshold. Every tool it calls is shown
        inline.
      </p>

      <div className="mt-8 flex flex-col items-start gap-2">
        {SUGGESTIONS.map((s, i) => (
          <button
            key={s}
            type="button"
            onClick={() => onPick(s)}
            style={{ animationDelay: `${i * 70}ms` }}
            className="animate-rise rounded-full border border-border bg-elevated px-4 py-2 text-left text-[0.8125rem] text-muted transition-all duration-fast ease hover:-translate-y-0.5 hover:border-ink/25 hover:text-ink hover:shadow-card"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
