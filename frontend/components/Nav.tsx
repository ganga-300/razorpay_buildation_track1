"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/cn";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/chat", label: "Chat" },
  { href: "/dashboard", label: "Dashboard" },
] as const;

export function Nav() {
  const pathname = usePathname();

  return (
    <header className="border-b border-border bg-elevated">
      <nav className="mx-auto flex max-w-6xl items-center gap-1 px-4 py-2.5">
        <Link href="/" className="mr-4 text-sm font-semibold tracking-tight">
          AutoBuy
        </Link>

        {LINKS.map((link) => {
          const active =
            link.href === "/"
              ? pathname === "/"
              : pathname.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "rounded-md px-2.5 py-1 text-sm transition-colors",
                active ? "bg-surface text-ink" : "text-muted hover:text-ink",
              )}
            >
              {link.label}
            </Link>
          );
        })}

        <span className="ml-auto hidden whitespace-nowrap rounded-full border border-border px-2 py-0.5 text-[11px] text-muted sm:inline-block">
          Razorpay test mode
        </span>
      </nav>
    </header>
  );
}
