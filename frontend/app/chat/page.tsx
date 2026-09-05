import { ChatWindow } from "@/components/chat/ChatWindow";

export const metadata = {
  title: "Chat — AutoBuy",
};

export default function ChatPage() {
  return (
    // 100dvh, not 100vh: on mobile 100vh includes the browser chrome, which
    // pushed the composer below the fold.
    <main className="mx-auto flex h-[calc(100dvh-4rem)] max-w-3xl flex-col px-5 pb-5 pt-2 sm:px-8">
      <ChatWindow />
    </main>
  );
}
