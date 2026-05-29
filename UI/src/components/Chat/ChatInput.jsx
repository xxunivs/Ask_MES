import { useState } from "react";
import { Send } from "lucide-react";

export default function ChatInput({ onSend, disabled, placeholder }) {
  const [text, setText] = useState("");

  function handleSubmit(e) {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      handleSubmit(e);
    }
  }

  return (
    <form className="chat-input-form" onSubmit={handleSubmit}>
      <textarea
        className="chat-textarea"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder || "자연어로 질문을 입력하세요... (Enter 전송)"}
        disabled={disabled}
        rows={1}
      />
      <button
        type="submit"
        className="chat-send-btn"
        disabled={disabled || !text.trim()}
      >
        <Send size={18} />
      </button>
    </form>
  );
}
