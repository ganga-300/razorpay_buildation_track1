import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";

export default function Loading() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <Card className="p-10 text-center text-sm text-muted">
        <Spinner /> Loading…
      </Card>
    </main>
  );
}
