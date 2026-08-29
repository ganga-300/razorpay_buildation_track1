"use client";

import { useCallback, useRef, useState } from "react";

import { streamChat } from "@/lib/sse";
import type { AgentIntent, Order } from "@/lib/types";
import type { ChatItem } from "./types";

let counter = 0;
const nextId = (prefix: string) => `${prefix}-${++counter}`;

/**
 * Drives one chat thread over the SSE endpoint.
 *
 * Tool calls and their results arrive as separate events, so pending calls are
 * tracked in a FIFO keyed by tool name: when a result arrives, it settles the
 * oldest unresolved call for that tool. That stays correct when the agent
 * issues several calls to the same tool in one turn.
 */
export function useChat() {
  const [items, setItems] = useState<ChatItem[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [intent, setIntent] = useState<AgentIntent | null>(null);

  const conversationId = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // tool name -> ids of calls still awaiting a result, oldest first
  const pendingTools = useRef<Map<string, string[]>>(new Map());

  const replaceOrder = useCallback((updated: Order) => {
    setItems((prev) =>
      prev.map((item) =>
        item.kind === "order" && item.order.order_id === updated.order_id
          ? { ...item, order: updated }
          : item,
      ),
    );
  }, []);

  const send = useCallback(async (text: string) => {
    const message = text.trim();
    if (!message) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    pendingTools.current = new Map();

    setItems((prev) => [
      ...prev,
      { kind: "user", id: nextId("user"), text: message },
    ]);
    setIsStreaming(true);

    try {
      for await (const event of streamChat({
        message,
        conversationId: conversationId.current,
        signal: controller.signal,
      })) {
        switch (event.event) {
          case "conversation":
            conversationId.current = event.data.conversation_id;
            break;

          case "intent":
            setIntent(event.data.intent);
            break;

          case "message":
            setItems((prev) => [
              ...prev,
              { kind: "agent", id: nextId("agent"), text: event.data.text },
            ]);
            break;

          case "tool_call": {
            const id = nextId("tool");
            const queue = pendingTools.current.get(event.data.tool) ?? [];
            pendingTools.current.set(event.data.tool, [...queue, id]);

            setItems((prev) => [
              ...prev,
              {
                kind: "tool",
                id,
                tool: event.data.tool,
                args: event.data.arguments,
                mutatesMoney: event.data.mutates_money,
                status: "running",
              },
            ]);
            break;
          }

          case "tool_result": {
            const queue = pendingTools.current.get(event.data.tool) ?? [];
            const [settledId, ...rest] = queue;
            pendingTools.current.set(event.data.tool, rest);
            if (!settledId) break;

            setItems((prev) =>
              prev.map((item) =>
                item.kind === "tool" && item.id === settledId
                  ? {
                      ...item,
                      status: event.data.ok ? "ok" : "error",
                      error: event.data.error,
                    }
                  : item,
              ),
            );
            break;
          }

          case "products":
            setItems((prev) => [
              ...prev,
              {
                kind: "products",
                id: nextId("products"),
                products: event.data.products,
              },
            ]);
            break;

          case "order":
            setItems((prev) => [
              ...prev,
              { kind: "order", id: nextId("order"), order: event.data.order },
            ]);
            break;

          case "error":
            setItems((prev) => [
              ...prev,
              { kind: "error", id: nextId("error"), error: event.data },
            ]);
            break;

          case "done":
          case "end":
            break;
        }
      }
    } catch (cause) {
      // An aborted stream is a deliberate cancellation, not a failure.
      if (controller.signal.aborted) return;

      setItems((prev) => [
        ...prev,
        {
          kind: "error",
          id: nextId("error"),
          error: {
            code: "stream_failed",
            message:
              cause instanceof Error
                ? cause.message
                : "The connection to the agent dropped.",
            retryable: true,
          },
        },
      ]);
    } finally {
      // Any tool still marked running never got a result; show it as failed
      // rather than leaving a spinner going forever.
      const orphaned = new Set(
        [...pendingTools.current.values()].flat(),
      );
      if (orphaned.size > 0) {
        setItems((prev) =>
          prev.map((item) =>
            item.kind === "tool" && orphaned.has(item.id)
              ? { ...item, status: "error" as const }
              : item,
          ),
        );
      }
      setIsStreaming(false);
    }
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    conversationId.current = null;
    pendingTools.current = new Map();
    setItems([]);
    setIntent(null);
    setIsStreaming(false);
  }, []);

  return { items, isStreaming, intent, send, reset, replaceOrder };
}
