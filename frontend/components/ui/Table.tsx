import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Right-align numeric columns so amounts line up on the decimal. */
  numeric?: boolean;
  render: (row: T) => ReactNode;
}

/**
 * Generic data table. The dashboard's orders table and Milestone 4's audit
 * table are both built from this, so column styling stays consistent.
 *
 * The wrapper scrolls horizontally on its own so a wide table never forces the
 * page body to scroll sideways on a phone.
 */
export function Table<T>({
  columns,
  rows,
  rowKey,
  empty = "Nothing to show yet.",
  className,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  empty?: ReactNode;
  className?: string;
}) {
  if (rows.length === 0) {
    return (
      <div className="px-4 py-10 text-center text-sm text-muted">{empty}</div>
    );
  }

  return (
    <div className={cn("w-full overflow-x-auto", className)}>
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border">
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={cn(
                  "whitespace-nowrap px-4 py-2.5 text-xs font-medium uppercase tracking-wide text-muted",
                  col.numeric ? "text-right" : "text-left",
                )}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              className="border-b border-border last:border-0"
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={cn(
                    "px-4 py-3 align-top",
                    col.numeric && "text-right tabular-nums",
                  )}
                >
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
