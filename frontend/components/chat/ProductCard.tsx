import { Card } from "@/components/ui/Card";
import { cn } from "@/lib/cn";
import type { Product } from "@/lib/types";

/** A product the agent surfaced mid-conversation. */
export function ProductCard({ product }: { product: Product }) {
  const { availability: stock } = product;

  return (
    <Card className="group p-4 transition-transform duration-slow ease hover:-translate-y-0.5 hover:shadow-lift">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-[0.875rem] font-semibold leading-snug tracking-[-0.015em]">
          {product.name}
        </h3>
        <span className="tabular whitespace-nowrap text-[0.9375rem] font-semibold tracking-[-0.02em]">
          {product.price.display}
        </span>
      </div>

      <p className="mt-2 line-clamp-2 text-[0.75rem] leading-relaxed text-muted">
        {product.description}
      </p>

      <div className="mt-3.5 flex flex-wrap items-center gap-2 text-[0.6875rem]">
        <span
          className={cn(
            "inline-flex items-center gap-1.5",
            stock.in_stock ? "text-muted" : "text-danger",
          )}
        >
          <span
            aria-hidden
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              stock.in_stock ? "bg-ok" : "bg-danger",
            )}
          />
          {stock.in_stock ? `${stock.quantity} in stock` : "Out of stock"}
        </span>
        <code className="ml-auto font-mono text-faint">{product.id}</code>
      </div>
    </Card>
  );
}

export function ProductGrid({ products }: { products: Product[] }) {
  if (products.length === 0) return null;

  return (
    <div className="grid gap-2.5 sm:grid-cols-2">
      {products.map((p) => (
        <ProductCard key={p.id} product={p} />
      ))}
    </div>
  );
}
