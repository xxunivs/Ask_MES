"use client";

import { useEffect, useRef, useState } from "react";
import { askQuestion } from "@/lib/api";
import ChatInput from "./ChatInput";
import ChatMessage, { type Message } from "./ChatMessage";
import FrequentQueries from "./FrequentQueries";

// 채팅 화면
export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(question: string) {
    const loadingId = Date.now() + 1;
    setMessages((prev) => [
      ...prev,
      { id: Date.now(), role: "user", text: question },
      { id: loadingId, role: "assistant", loading: true },
    ]);
    setLoading(true);

    let reply: Message;
    try {
      const result = await askQuestion(question);
      reply = { id: loadingId, role: "assistant", result };
    } catch (e) {
      const text = e instanceof Error ? e.message : "다시 시도해 주세요.";
      reply = { id: loadingId, role: "assistant", text: `오류: ${text}` };
    }
    setMessages((prev) => prev.map((m) => (m.id === loadingId ? reply : m)));
    setLoading(false);
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-4xl flex-col">
      <header className="px-6 pt-8 pb-4">
        <h1 className="text-[28px] leading-[1.14] font-medium tracking-[-0.63px]">Ask MES!</h1>
        <p className="mt-1 text-sm text-ink-mute">MES 데이터 조회 시스템</p>
      </header>

      <main className="flex-1 space-y-4 overflow-y-auto px-6 py-4">
        {messages.map((m) => (
          <ChatMessage key={m.id} message={m} />
        ))}
        <div ref={bottomRef} />
      </main>

      <footer className="space-y-3 border-t border-hairline bg-canvas px-6 py-4">
        <FrequentQueries onSelect={handleSend} disabled={loading} />
        <ChatInput onSend={handleSend} disabled={loading} />
      </footer>
    </div>
  );
}
