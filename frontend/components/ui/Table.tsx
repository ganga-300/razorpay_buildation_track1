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
      <div className="px-5 py-16 text-center text-[0.8125rem] text-muted">
        {empty}
      </div>
    );
  }

  return (
    // `contain: paint` keeps this scroller's overflow out of the root
    // scrollWidth. Without it a wide table inflates the document by the
    // overflow amount and the whole page picks up a stray horizontal scroll,
    // even though the table itself is clipped and scrolls correctly.
    <div className={cn("w-full overflow-x-auto [contain:paint]", className)}>
      <table className="w-full border-collapse text-[0.8125rem]">
        <thead>
          <tr className="border-b border-border">
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={cn(
                  "whitespace-nowrap px-5 py-3 text-eyebrow uppercase text-faint",
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
              className="border-b border-border transition-colors duration-fast ease last:border-0 hover:bg-sunken/60"
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={cn(
                    "px-5 py-4 align-top",
                    col.numeric && "tabular text-right",
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
