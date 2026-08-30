"use client";

import { useEffect, useRef } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
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
    <Card className="flex h-full min-h-0 flex-col overflow-hidden">
      <CardHeader
        title="Purchasing agent"
        subtitle="Razorpay test mode · every money action is bounded and audited"
        action={
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
            {items.length > 0 ? (
              <Button variant="ghost" size="sm" onClick={reset}>
                New chat
              </Button>
            ) : null}
          </div>
        }
      />

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {items.length === 0 ? (
          <EmptyState onPick={send} />
        ) : (
          items.map((item) => (
            <ChatItemView key={item.id} item={item} onSettled={replaceOrder} />
          ))
        )}
      </div>

      <Composer onSend={send} disabled={isStreaming} />
    </Card>
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
      return (
        <GuardrailNotice decision={item.decision} blocked={item.blocked} />
      );

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
        <div className="rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-xs text-danger">
          <span className="font-mono font-medium">{item.error.code}</span>
          {" — "}
          {item.error.message}
        </div>
      );
  }
}

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
      <div>
        <p className="text-sm font-medium">Tell the agent what you need.</p>
        <p className="mt-1 text-xs text-muted">
          It searches the catalog, proposes an order, and asks before spending
          above the approval threshold.
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((s) => (
          <Button key={s} variant="secondary" size="sm" onClick={() => onPick(s)}>
            {s}
          </Button>
        ))}
      </div>
    </div>
  );
}
