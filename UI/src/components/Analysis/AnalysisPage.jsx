import { useState, useRef, useEffect } from "react";
import { BarChart2 } from "lucide-react";
import StatisticsView from "./StatisticsView";
import ChatInput from "../Chat/ChatInput";
import ChatMessage from "../Chat/ChatMessage";
import { getAnalysisResponse } from "../../utils/nlToSql";

function now() {
  return new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

export default function AnalysisPage({ sqlInfo }) {
  // sqlInfo: { sql, description, data: { columns, rows, count } }
  const actualData = sqlInfo?.data || null;

  const [messages, setMessages] = useState([
    {
      id: 0,
      role: "assistant",
      type: "text",
      content: actualData
        ? `원본 데이터가 조회되었습니다. (${actualData.count ?? actualData.rows?.length ?? 0}행)\n통계 분석이 필요하시면 질문해 주세요.\n예) "불량률이 가장 높은 항목은?", "평균과 최솟값 알려줘"`
        : `원본 데이터를 불러오지 못했습니다.\n아래에서 데이터에 대해 질문하시면 Ollama가 분석해 드립니다.`,
      time: now(),
    },
  ]);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(text) {
    const userMsg = { id: Date.now(), role: "user", type: "text", content: text, time: now() };
    const loadingMsg = { id: Date.now() + 1, role: "assistant", type: "loading", time: "" };
    setMessages((prev) => [...prev, userMsg, loadingMsg]);
    setLoading(true);

    try {
      // 실제 데이터를 Ollama 분석으로 전달
      const answer = await getAnalysisResponse(text, actualData);
      setMessages((prev) =>
        prev.filter((m) => m.type !== "loading").concat({
          id: Date.now() + 2,
          role: "assistant",
          type: "text",
          content: answer.content,
          time: now(),
        })
      );
    } catch (e) {
      setMessages((prev) =>
        prev.filter((m) => m.type !== "loading").concat({
          id: Date.now() + 2,
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

  return (
    <div className="analysis-page">
      {/* 헤더 */}
      <div className="analysis-header">
        <BarChart2 size={20} className="header-icon" />
        <div>
          <h2 className="analysis-title">데이터 분석</h2>
          <p className="analysis-sub">{sqlInfo?.description}</p>
        </div>
      </div>

      {/* 좌우 분할 레이아웃 */}
      <div className="analysis-layout">
        {/* 왼쪽: 통계 뷰 */}
        <div className="analysis-left">
          <StatisticsView sqlInfo={sqlInfo} tableData={actualData} />
        </div>

        {/* 오른쪽: 분석 채팅 */}
        <div className="analysis-right">
          <p className="analysis-chat-label">데이터 질문 (Ollama 분석)</p>
          <div className="analysis-messages">
            {messages.map((msg) => (
              <ChatMessage key={msg.id} msg={msg} />
            ))}
            <div ref={bottomRef} />
          </div>
          <ChatInput
            onSend={handleSend}
            disabled={loading}
            placeholder="데이터에 대해 질문하세요..."
          />
        </div>
      </div>
    </div>
  );
}
