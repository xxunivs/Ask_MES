import { Bot, User, CheckCircle, XCircle, BarChart2 } from "lucide-react";

export default function ChatMessage({ msg, onConfirm, onCancel, onStatsConfirm, onStatsCancel }) {
  const isUser = msg.role === "user";

  return (
    <div className={`chat-message ${isUser ? "user" : "assistant"}`}>
      <div className="msg-avatar">
        {isUser ? <User size={16} /> : <Bot size={16} />}
      </div>

      <div className="msg-bubble">
        {/* 일반 텍스트 */}
        {msg.type === "text" && (
          <p className="msg-text">{msg.content}</p>
        )}

        {/* SQL 확인 요청 */}
        {msg.type === "sql-confirm" && (
          <div className="sql-confirm">
            <p className="sql-desc">{msg.description}</p>
            <p className="sql-subtitle">다음 SQL을 실행할까요?</p>
            <pre className="sql-code">{msg.sql}</pre>
            {msg.pending && (
              <div className="sql-actions">
                <button className="btn-confirm" onClick={onConfirm}>
                  <CheckCircle size={15} /> 실행 확인
                </button>
                <button className="btn-cancel" onClick={onCancel}>
                  <XCircle size={15} /> 취소
                </button>
              </div>
            )}
            {!msg.pending && msg.confirmed && (
              <p className="sql-confirmed">✅ SQL 실행이 확인되었습니다.</p>
            )}
            {!msg.pending && !msg.confirmed && (
              <p className="sql-cancelled">❌ 취소되었습니다.</p>
            )}
          </div>
        )}

        {/* 데이터 테이블 */}
        {msg.type === "data-table" && (
          <div className="data-table-wrap">
            <p className="sql-desc">SQL 실행 결과</p>
            <div className="data-table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    {msg.tableData.columns.map((col) => (
                      <th key={col}>{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {msg.tableData.rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td key={j}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* 통계 화면 이동 확인 */}
        {msg.type === "stats-confirm" && (
          <div className="sql-confirm">
            <p className="sql-desc">데이터를 통계 화면에서 시각화할까요?</p>
            {msg.pending && (
              <div className="sql-actions">
                <button className="btn-confirm" onClick={onStatsConfirm}>
                  <BarChart2 size={15} /> 통계 화면으로 이동
                </button>
                <button className="btn-cancel" onClick={onStatsCancel}>
                  <XCircle size={15} /> 괜찮아요
                </button>
              </div>
            )}
            {!msg.pending && msg.confirmed && (
              <p className="sql-confirmed">✅ 통계 화면으로 이동합니다.</p>
            )}
            {!msg.pending && !msg.confirmed && (
              <p className="sql-cancelled">채팅에서 계속 분석하세요.</p>
            )}
          </div>
        )}

        {/* 로딩 */}
        {msg.type === "loading" && (
          <div className="msg-loading">
            <span /><span /><span />
          </div>
        )}

        <span className="msg-time">{msg.time}</span>
      </div>
    </div>
  );
}
