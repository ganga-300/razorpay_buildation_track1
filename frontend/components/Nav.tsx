"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { cn } from "@/lib/cn";

const LINKS = [
  { href: "/chat", label: "Chat" },
  { href: "/dashboard", label: "Dashboard" },
] as const;

/**
 * Thin, uppercase, letterspaced — the reference's nav treatment.
 *
 * It gains a border and a blurred backdrop only after the page scrolls, so the
 * hero opens against an unbroken field of paper and the chrome appears when it
 * starts to be needed.
 */
export function Nav() {
  const pathname = usePathname();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={cn(
        "sticky top-0 z-50 transition-all duration-slow ease",
        scrolled
          ? "border-b border-border bg-surface/80 backdrop-blur-xl"
          : "border-b border-transparent bg-transparent",
      )}
    >
      <nav className="mx-auto flex h-16 max-w-6xl items-center gap-8 px-5 sm:px-8">
        <Link
          href="/"
          className="text-[0.9375rem] font-semibold tracking-[-0.03em] transition-opacity duration-fast hover:opacity-60"
        >
          autobuy
        </Link>

        <div className="flex items-center gap-6">
          {LINKS.map((link) => {
            const active = pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative text-eyebrow uppercase transition-colors duration-fast",
                  active ? "text-ink" : "text-faint hover:text-ink",
                )}
              >
                {link.label}
                {/* The active marker slides in rather than blinking on. */}
                <span
                  className={cn(
                    "absolute -bottom-1.5 left-0 h-px bg-ink transition-all duration-slow ease",
                    active ? "w-full opacity-100" : "w-0 opacity-0",
                  )}
                />
              </Link>
            );
          })}
        </div>

        <span className="ml-auto hidden items-center gap-2 text-eyebrow uppercase text-faint sm:flex">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-ok" />
          Razorpay test mode
        </span>
      </nav>
    </header>
  );
}
