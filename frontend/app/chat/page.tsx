import { ChatWindow } from "@/components/chat/ChatWindow";

export const metadata = {
  title: "Chat — AutoBuy",
};

export default function ChatPage() {
  return (
    // 100dvh, not 100vh: on mobile 100vh includes the browser chrome, which
    // pushed the composer below the fold.
    <main className="mx-auto flex h-[calc(100dvh-3.25rem)] max-w-3xl flex-col px-4 py-4">
      <div className="mb-4 shrink-0">
        <h1 className="text-xl font-semibold tracking-tight">
          Conversational checkout
        </h1>
        <p className="mt-1 text-sm text-muted">
          Every tool the agent calls is shown inline, with money-moving calls
          marked. Nothing happens that you cannot see.
        </p>
      </div>

      <div className="min-h-0 flex-1">
        <ChatWindow />
      </div>
    </main>
  );
}
