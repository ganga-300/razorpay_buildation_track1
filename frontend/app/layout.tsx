import type { Metadata } from "next";

import { Nav } from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "AutoBuy — Agentic Commerce",
  description:
    "An AI purchasing agent that discovers a merchant catalog, converses with a buyer, and completes a real Razorpay test-mode purchase — bounded, gated, and fully audited.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <Nav />
        {children}
      </body>
    </html>
  );
}
