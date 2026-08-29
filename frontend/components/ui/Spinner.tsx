import { cn } from "@/lib/cn";

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn(
        "inline-block h-3 w-3 animate-spin rounded-full",
        "border-2 border-current border-r-transparent align-[-1px]",
        className,
      )}
    />
  );
}
