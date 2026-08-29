import { Badge } from "@/components/ui/Badge";
import { Table, type Column } from "@/components/ui/Table";
import { statusOf } from "@/lib/orderStatus";
import type { Order } from "@/lib/types";

function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

const COLUMNS: Column<Order>[] = [
  {
    key: "order",
    header: "Order",
    render: (o) => (
      <div className="min-w-0">
        <code className="block font-mono text-xs">{o.order_id}</code>
        {o.razorpay_order_id ? (
          <code className="mt-0.5 block font-mono text-[11px] text-muted">
            {o.razorpay_order_id}
          </code>
        ) : (
          <span className="text-[11px] text-muted">never reached Razorpay</span>
        )}
      </div>
    ),
  },
  {
    key: "product",
    header: "Product",
    render: (o) => (
      <div className="min-w-0">
        <span className="block truncate">{o.product.name}</span>
        <span className="text-xs text-muted">
          {o.quantity} × {o.unit_price.display}
        </span>
      </div>
    ),
  },
  {
    key: "total",
    header: "Total",
    numeric: true,
    render: (o) => <span className="font-medium">{o.total.display}</span>,
  },
  {
    key: "status",
    header: "Status",
    render: (o) => {
      const s = statusOf(o.status);
      return (
        <div>
          <Badge tone={s.tone}>{s.label}</Badge>
          {o.failure?.code ? (
            <p className="mt-1 max-w-[22rem] text-[11px] text-danger">
              <span className="font-mono">{o.failure.code}</span>
              {o.failure.reason ? ` — ${o.failure.reason}` : null}
            </p>
          ) : null}
        </div>
      );
    },
  },
  {
    key: "attempts",
    header: "Tries",
    numeric: true,
    render: (o) => <span className="text-muted">{o.attempts}</span>,
  },
  {
    key: "created",
    header: "Created",
    render: (o) => (
      <span className="whitespace-nowrap text-xs text-muted">
        {formatWhen(o.created_at)}
      </span>
    ),
  },
];

export function OrdersTable({ orders }: { orders: Order[] }) {
  return (
    <Table
      columns={COLUMNS}
      rows={orders}
      rowKey={(o) => o.order_id}
      empty="No orders yet. Start a conversation on the chat page."
    />
  );
}
