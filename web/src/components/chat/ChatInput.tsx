"use client";

import { useState } from "react";

// 질문 입력칸과 보내기 버튼
export default function ChatInput({
  onSend,
  disabled,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
}) {
  const [text, setText] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const question = text.trim();
    if (!question || disabled) return;
    onSend(question);
    setText("");
  }

  return (
    <form onSubmit={submit} className="flex gap-2">
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="MES 데이터에 대해 질문하세요."
        className="flex-1 rounded-md border border-[#cfd3d9] bg-white px-3 py-2.5 text-base shadow-[inset_0_1px_3px_rgba(0,0,0,0.10)] outline-none focus:border-primary focus:shadow-[inset_0_1px_3px_rgba(0,0,0,0.10),0_0_0_3px_rgba(27,25,56,0.12)]"
      />
      <button
        type="submit"
        disabled={disabled}
        className="rounded-md border border-primary-deep bg-gradient-to-b from-[#2e2b55] to-primary px-5 py-3 text-sm font-semibold text-white shadow-[0_2px_4px_rgba(0,0,0,0.25),inset_0_1px_0_rgba(255,255,255,0.15)] hover:to-primary-deep active:translate-y-px active:shadow-inner disabled:opacity-40"
      >
        보내기
      </button>
    </form>
  );
}
