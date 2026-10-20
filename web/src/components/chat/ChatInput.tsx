"use client";

import { useState } from "react";

// 질문 입력창
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
        placeholder="MES 데이터에 대해 질문하세요 (예: 홀드 상태인 LOT 목록 보여줘)"
        className="flex-1 rounded-sm border border-hairline bg-canvas px-3 py-2.5 text-base outline-none focus:border-primary"
      />
      <button
        type="submit"
        disabled={disabled}
        className="rounded-md bg-primary px-5 py-3 text-sm font-semibold text-white hover:bg-primary-deep disabled:opacity-40"
      >
        보내기
      </button>
    </form>
  );
}
