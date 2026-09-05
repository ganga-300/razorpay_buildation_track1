import type { Metadata } from "next";

import { MotionProvider } from "@/components/motion/MotionProvider";
import { Nav } from "@/components/Nav";
import { mono, sans } from "./fonts";
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
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body className="min-h-screen antialiased">
        <MotionProvider />
        <Nav />
        {children}
      </body>
    </html>
  );
}
