import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import type { Product } from "@/lib/types";

/** A product the agent surfaced mid-conversation. */
export function ProductCard({ product }: { product: Product }) {
  const { availability: stock } = product;

  return (
    <Card className="p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-medium">{product.name}</h3>
          <p className="mt-0.5 text-xs text-muted">{product.category}</p>
        </div>
        <span className="whitespace-nowrap text-sm font-semibold tabular-nums">
          {product.price.display}
        </span>
      </div>

      <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-muted">
        {product.description}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Badge tone={stock.in_stock ? "ok" : "danger"}>
          {stock.in_stock ? `${stock.quantity} in stock` : "Out of stock"}
        </Badge>
        <code className="rounded bg-surface px-1.5 py-0.5 font-mono text-[11px] text-muted">
          {product.id}
        </code>
      </div>
    </Card>
  );
}

export function ProductGrid({ products }: { products: Product[] }) {
  if (products.length === 0) return null;

  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {products.map((p) => (
        <ProductCard key={p.id} product={p} />
      ))}
    </div>
  );
}
