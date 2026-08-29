import type { ErrorPayload, Order, Product } from "@/lib/types";
import type { ToolStatus } from "./ToolTrace";

/** One rendered entry in the transcript. */
export type ChatItem =
  | { kind: "user"; id: string; text: string }
  | { kind: "agent"; id: string; text: string }
  | {
      kind: "tool";
      id: string;
      tool: string;
      args: Record<string, unknown>;
      mutatesMoney: boolean;
      status: ToolStatus;
      error?: ErrorPayload | null;
    }
  | { kind: "products"; id: string; products: Product[] }
  | { kind: "order"; id: string; order: Order }
  | { kind: "error"; id: string; error: ErrorPayload };
