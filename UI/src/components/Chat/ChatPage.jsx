import { useState, useRef, useEffect } from "react";
import { Database } from "lucide-react";
import FrequentQueries from "./FrequentQueries";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import { convertNlToSql } from "../../utils/nlToSql";

function now() {
  return new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

/** mes-api 반환 rows(dict 배열) → 2차원 배열 변환 */
function normalizeTableData(data) {
  if (!data || !data.columns || !data.rows) return null;
  const { columns, rows, count } = data;
  const arr = rows.map((row) =>
    columns.map((col) => {
      const v = row[col];
      return v === null || v === undefined ? "" : v;
    })
  );
  return { columns, rows: arr, count };
}

export default function ChatPage({ onSqlConfirmed }) {
  const [messages, setMessages] = useState([
    {
      id: 0,
      role: "assistant",
      type: "text",
      content:
        "안녕하세요! MES AI 어시스턴트입니다.\n자연어로 질문하시면 SQL로 변환해 드립니다.",
      time: now(),
    },
  ]);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(text) {
    const userMsg = {
      id: Date.now(),
      role: "user",
      type: "text",
      content: text,
      time: now(),
    };
    const loadingMsg = { id: Date.now() + 1, role: "assistant", type: "loading", time: "" };

    setMessages((prev) => [...prev, userMsg, loadingMsg]);
    setLoading(true);

    try {
      const result = await convertNlToSql(text, 100);
      const sqlMsg = {
        id: Date.now() + 2,
        role: "assistant",
        type: "sql-confirm",
        sql: result.sql,
        description: result.description,
        data: result.data,        // 실제 DB 데이터 (또는 null)
        db_error: result.db_error,
        pending: true,
        confirmed: false,
        time: now(),
      };
      setMessages((prev) => prev.filter((m) => m.type !== "loading").concat(sqlMsg));
    } catch (e) {
      setMessages((prev) =>
        prev.filter((m) => m.type !== "loading").concat({
          id: Date.now() + 3,
          role: "assistant",
          type: "text",
          content: `오류: ${e.message || "다시 시도해 주세요."}`,
          time: now(),
        })
      );
    } finally {
      setLoading(false);
    }
  }

  function handleConfirm(msgId) {
    const confirmed = messages.find((m) => m.id === msgId);
    const tableId = Date.now() + 10;
    const statsId = Date.now() + 11;

    // 실제 DB 데이터 → 2차원 배열 정규화
    const tableData = normalizeTableData(confirmed?.data);

    setMessages((prev) => [
      ...prev.map((m) =>
        m.id === msgId ? { ...m, pending: false, confirmed: true } : m
      ),
      ...(tableData
        ? [
            {
              id: tableId,
              role: "assistant",
              type: "data-table",
              tableData,
              time: now(),
            },
          ]
        : confirmed?.db_error
        ? [
            {
              id: tableId,
              role: "assistant",
              type: "text",
              content: `⚠️ DB 실행 오류: ${confirmed.db_error}\nSQL은 생성되었으나 데이터를 가져오지 못했습니다.`,
              time: now(),
            },
          ]
        : []),
      {
        id: statsId,
        role: "assistant",
        type: "stats-confirm",
        sqlMsg: confirmed,
        pending: true,
        time: now(),
      },
    ]);
  }

  function handleStatsConfirm(msgId) {
    const statsMsg = messages.find((m) => m.id === msgId);
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId ? { ...m, pending: false, confirmed: true } : m
      )
    );
    if (statsMsg?.sqlMsg) onSqlConfirmed(statsMsg.sqlMsg);
  }

  function handleStatsCancel(msgId) {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId ? { ...m, pending: false, confirmed: false } : m
      )
    );
  }

  function handleCancel(msgId) {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId ? { ...m, pending: false, confirmed: false } : m
      )
    );
  }

  const hasPendingSql = messages.some(
    (m) => (m.type === "sql-confirm" || m.type === "stats-confirm") && m.pending
  );

  return (
    <div className="chat-page">
      {/* 헤더 */}
      <div className="chat-header">
        <div className="chat-header-left">
          <Database size={22} className="header-icon" />
          <div>
            <h1 className="header-title">MES AI 어시스턴트</h1>
            <p className="header-sub">자연어 → SQL 변환 · 데이터 분석</p>
          </div>
        </div>
        <div className="chat-header-right">
          <div className="header-badge">NeuroFactory</div>
        </div>
      </div>

      {/* 자주 묻는 질문 */}
      <FrequentQueries onSelect={handleSend} />

      {/* 메시지 목록 */}
      <div className="chat-messages">
        {messages.map((msg) => (
          <ChatMessage
            key={msg.id}
            msg={msg}
            onConfirm={() => handleConfirm(msg.id)}
            onCancel={() => handleCancel(msg.id)}
            onStatsConfirm={() => handleStatsConfirm(msg.id)}
            onStatsCancel={() => handleStatsCancel(msg.id)}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* 입력창 */}
      <div className="chat-input-area">
        {hasPendingSql && (
          <p className="pending-notice">⚠ SQL 확인 후 새 질문을 입력할 수 있습니다.</p>
        )}
        <ChatInput onSend={handleSend} disabled={loading || hasPendingSql} />
      </div>
    </div>
  );
}
