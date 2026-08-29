import type {
  BoundCheck,
  ErrorPayload,
  GuardrailDecision,
  Money,
  Order,
  Product,
} from "@/lib/types";
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
  | {
      kind: "guardrail";
      id: string;
      decision: GuardrailDecision;
      blocked: boolean;
    }
  | {
      kind: "approval";
      id: string;
      orderId: string;
      total: Money;
      productName: string;
      reason: string | null;
      checks: BoundCheck[];
    }
  | { kind: "error"; id: string; error: ErrorPayload };
