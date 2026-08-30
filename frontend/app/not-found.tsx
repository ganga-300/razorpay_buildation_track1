import Link from "next/link";

import { Card } from "@/components/ui/Card";

export default function NotFound() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-16">
      <Card className="p-6">
        <h1 className="text-lg font-semibold">Page not found</h1>
        <p className="mt-2 text-sm text-muted">
          That route does not exist.
        </p>
        <div className="mt-4 flex gap-4 text-sm">
          <Link href="/chat" className="text-brand hover:underline">
            Talk to the agent
          </Link>
          <Link href="/dashboard" className="text-brand hover:underline">
            Merchant dashboard
          </Link>
        </div>
      </Card>
    </main>
  );
}
